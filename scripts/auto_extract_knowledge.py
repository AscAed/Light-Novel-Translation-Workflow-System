import os
import sys
import json
import asyncio
from pathlib import Path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline import Config, get_openai_client, get_api_key, get_chapters
from utils import read_child_text, write_new_child_text

async def extract_knowledge(raw_dir: str, output_dir: str):
    print("Starting experimental knowledge extraction...")
    chapters = get_chapters(raw_dir)
    if not chapters:
        print("No raw chapters found.")
        return

    draft_names = ("Glossary_draft.json", "STORY_SUMMARY_draft.md")
    for draft_name in draft_names:
        draft_path = Path(output_dir) / draft_name
        if draft_path.exists() or draft_path.is_symlink():
            raise FileExistsError(f"Draft already exists and will not be overwritten: {draft_path}")
        
    # Read first 3 chapters for context
    sample_text = ""
    for chap in chapters[:3]:
        sample_text += f"\n\n--- {chap} ---\n\n"
        sample_text += read_child_text(raw_dir, chap)
        
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

    client = get_openai_client(Config.DEEPSEEK_BASE_URL, get_api_key("DEEPSEEK_API_KEY"))
    
    print("Calling LLM for analysis...")
    try:
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
        
        os.makedirs(output_dir, exist_ok=True)
        
        glossary_path = os.path.join(output_dir, "Glossary_draft.json")
        summary_path = os.path.join(output_dir, "STORY_SUMMARY_draft.md")
        
        glossary_dict = {}
        for item in result_json.get("glossary", []):
            if "src" in item and "dst" in item:
                # Formatting as dictionary per original schema, but keeping info if needed
                val = item["dst"]
                if item.get("info"):
                    val += f" （{item['info']}）"
                glossary_dict[item["src"]] = val
                
        write_new_child_text(
            output_dir,
            os.path.basename(glossary_path),
            json.dumps(glossary_dict, ensure_ascii=False, indent=2),
        )
        write_new_child_text(
            output_dir,
            os.path.basename(summary_path),
            f"# Story Summary (Draft)\n\n{result_json.get('summary', '')}",
        )
            
        print(f"Extraction complete!\nDraft glossary saved to: {glossary_path}\nDraft summary saved to: {summary_path}")
        
    except Exception as e:
        print(f"Error during extraction: {e}")
        raise

if __name__ == "__main__":
    Config.load_config()
    knowledge_dir = os.path.join(Config.WORKSPACE_DIR, "Knowledge")
    asyncio.run(extract_knowledge(Config.RAW_DIR, knowledge_dir))
