import os
import sys
import json
import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline import (
    Config,
    get_api_key,
    get_chapter_specs,
    get_chapters,
    get_openai_client,
)
from utils import (
    read_child_text,
    read_relative_text,
    split_paragraphs,
    write_new_child_text,
)


def _validate_extraction_result(result_json):
    if not isinstance(result_json, dict):
        raise ValueError("Knowledge extraction response must be a JSON object.")

    glossary = result_json.get("glossary")
    summary = result_json.get("summary")
    if not isinstance(glossary, list):
        raise ValueError("Knowledge extraction response must contain a glossary array.")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("Knowledge extraction response must contain a non-empty summary.")

    validated_glossary = []
    seen_terms = {}
    for index, item in enumerate(glossary, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Glossary item {index} must be an object.")

        source_term = item.get("src")
        translated_term = item.get("dst")
        info = item.get("info", "")
        if not isinstance(source_term, str) or not source_term.strip():
            raise ValueError(f"Glossary item {index} must contain a non-empty src.")
        if not isinstance(translated_term, str) or not translated_term.strip():
            raise ValueError(f"Glossary item {index} must contain a non-empty dst.")
        if not isinstance(info, str):
            raise ValueError(f"Glossary item {index} info must be text.")

        source_term = source_term.strip()
        translated_term = translated_term.strip()
        info = info.strip()
        value = f"{translated_term} （{info}）" if info else translated_term
        previous_value = seen_terms.get(source_term)
        if previous_value is not None and previous_value != value:
            raise ValueError(
                f"Glossary contains conflicting translations for source term "
                f"at item {index}."
            )
        if previous_value is None:
            seen_terms[source_term] = value
            validated_glossary.append((source_term, value))

    return validated_glossary, summary.strip()


def _sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_provenance_manifest(chapter_inputs, sample_text, glossary_entries, model):
    source_files = []
    paragraphs_by_chapter = {}
    for chapter in chapter_inputs:
        sent_start = min(chapter["content_start"], len(sample_text))
        sent_end = min(chapter["content_end"], len(sample_text))
        sent_text = sample_text[sent_start:sent_end]
        if not sent_text:
            continue

        paragraphs = split_paragraphs(sent_text)
        paragraphs_by_chapter[chapter["filename"]] = paragraphs
        source_files.append(
            {
                "filename": chapter["filename"],
                "tm_key": chapter.get("tm_key", chapter["filename"]),
                "source_sha256": _sha256_text(chapter["content"]),
                "included_characters": len(sent_text),
                "included_sha256": _sha256_text(sent_text),
                "included_paragraph_count": len(paragraphs),
            }
        )

    glossary_evidence = []
    for source_term, _ in glossary_entries:
        occurrences = []
        for filename, paragraphs in paragraphs_by_chapter.items():
            paragraph_indices = [
                index
                for index, paragraph in enumerate(paragraphs, start=1)
                if source_term in paragraph
            ]
            if paragraph_indices:
                occurrences.append(
                    {"chapter": filename, "paragraph_indices": paragraph_indices}
                )
        glossary_evidence.append(
            {"src": source_term, "occurrences": occurrences}
        )

    return {
        "schema_version": 1,
        "artifact_status": "complete",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "producer": {
            "script": "scripts/auto_extract_knowledge.py",
            "provider_id": "deepseek",
            "model": model,
        },
        "prompt_sample_sha256": _sha256_text(sample_text),
        "source_files": source_files,
        "glossary_evidence": glossary_evidence,
        "summary_source_chapters": [
            source["filename"] for source in source_files
        ],
    }


async def extract_knowledge(raw_dir: str, output_dir: str):
    print("Starting experimental knowledge extraction...")
    if Config.CHAPTER_MAP is None:
        chapters = get_chapters(raw_dir)
    else:
        chapters = get_chapter_specs(
            raw_dir, Config.OUTPUT_DIR, Config.CHAPTER_MAP
        )
    if not chapters:
        print("No raw chapters found.")
        return

    draft_names = (
        "Glossary_draft.json",
        "STORY_SUMMARY_draft.md",
        "KNOWLEDGE_PROVENANCE_draft.json",
    )
    for draft_name in draft_names:
        draft_path = Path(output_dir) / draft_name
        if draft_path.exists() or draft_path.is_symlink():
            raise FileExistsError(f"Draft already exists and will not be overwritten: {draft_path}")
        
    # Read first 3 chapters for context
    sample_text = ""
    chapter_inputs = []
    for chapter in chapters[:3]:
        if isinstance(chapter, str):
            raw_file = chapter
            tm_key = chapter
            content = read_child_text(raw_dir, raw_file)
        else:
            raw_file = chapter.raw_file
            tm_key = chapter.tm_key
            content = read_relative_text(raw_dir, raw_file)
        section_header = f"\n\n--- {raw_file} ---\n\n"
        content_start = len(sample_text) + len(section_header)
        sample_text += section_header + content
        chapter_inputs.append(
            {
                "filename": raw_file,
                "tm_key": tm_key,
                "content": content,
                "content_start": content_start,
                "content_end": content_start + len(content),
            }
        )
        
    # Limit sample size to avoid token overflow
    if len(sample_text) > 20000:
        sample_text = sample_text[:20000]
        
    prompt = (
        "你是一个专门分析日语轻小说设定的助手。请仔细阅读以下小说的前几章内容，并提取出核心信息。\n"
        "你需要返回两部分信息：\n"
        "1. 术语表（Glossary）：包括出场人物名、地名、专有名词、特殊技能等。请提供日文原词（src）、中文翻译建议（dst）以及简短的备注说明（info）。\n"
        "2. 剧情概要（Story Summary）：简明扼要地总结这几章的情节发展。\n\n"
        "请严格按以下JSON格式返回：\n"
        "{\n"
        "  \"glossary\": [\n"
        "    {\"src\": \"日文名词\", \"dst\": \"中文译名\", \"info\": \"简短说明，如：男主角/地名\"}\n"
        "  ],\n"
        "  \"summary\": \"剧情概要文本...\"\n"
        "}\n\n"
        f"[小说内容]\n{sample_text}"
    )

    client = get_openai_client(
        Config.DEEPSEEK_BASE_URL,
        get_api_key("DEEPSEEK_API_KEY"),
        provider_id="deepseek",
        data_categories={"source_text"},
    )

    print("Calling LLM for analysis...")
    response = await client.chat.completions.create(
        model=Config.PROOFREAD_MODEL, # Flash is good enough for extraction
        messages=[
            {"role": "system", "content": "你是一个专业的日文轻小说设定提取器。"},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )

    result_text = response.choices[0].message.content
    result_json = json.loads(result_text)
    glossary_entries, summary = _validate_extraction_result(result_json)
    glossary_dict = dict(glossary_entries)
    provenance_manifest = _build_provenance_manifest(
        chapter_inputs,
        sample_text,
        glossary_entries,
        Config.PROOFREAD_MODEL,
    )
    os.makedirs(output_dir, exist_ok=True)
    glossary_path = os.path.join(output_dir, "Glossary_draft.json")
    summary_path = os.path.join(output_dir, "STORY_SUMMARY_draft.md")
    provenance_path = os.path.join(
        output_dir, "KNOWLEDGE_PROVENANCE_draft.json"
    )

    write_new_child_text(
        output_dir,
        os.path.basename(glossary_path),
        json.dumps(glossary_dict, ensure_ascii=False, indent=2),
    )
    write_new_child_text(
        output_dir,
        os.path.basename(summary_path),
        f"# Story Summary (Draft)\n\n{summary}",
    )
    write_new_child_text(
        output_dir,
        os.path.basename(provenance_path),
        json.dumps(provenance_manifest, ensure_ascii=False, indent=2),
    )
        
    print(
        "Extraction complete!\n"
        f"Draft glossary saved to: {glossary_path}\n"
        f"Draft summary saved to: {summary_path}\n"
        f"Draft provenance saved to: {provenance_path}"
    )
        
def main():
    try:
        Config.load_config()
        knowledge_dir = os.path.join(Config.WORKSPACE_DIR, "Knowledge")
        asyncio.run(extract_knowledge(Config.RAW_DIR, knowledge_dir))
    except Exception as exc:
        print(
            f"Error during extraction ({type(exc).__name__}).",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
