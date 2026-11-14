import argparse
import os
import json
import re
from typing import List, Dict, Any, Optional
from utils import extract_chapter_num

# Robust Glossary Parser
def load_glossary(path: str) -> Dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Remove single-line comments starting with //
    content_clean = re.sub(r'//.*', '', content)
    
    decoder = json.JSONDecoder()
    pos = 0
    merged = {}
    content_clean = content_clean.strip()
    while pos < len(content_clean):
        start = content_clean.find('{', pos)
        if start == -1:
            break
        try:
            obj, idx = decoder.raw_decode(content_clean[start:])
            if isinstance(obj, dict):
                merged.update(obj)
            pos = start + idx
        except json.JSONDecodeError as e:
            # If parsing fails, move forward to find next '{'
            pos = start + 1
    return merged

# 2. Define functions
def extract_match_keywords(key: str) -> List[str]:
    # Remove content inside brackets, braces, and parentheses
    clean = re.sub(r'[\(\（\[\]\{\}].*?[\)\）\[\]\{\}]', '', key)
    parts = re.split(r'[/／or,，、]', clean)
    results = []
    for p in parts:
        stripped = p.strip()
        if len(stripped) >= 1:
            results.append(stripped)
    return results

def filter_glossary(raw_text: str, full_glossary: Dict[str, Any]) -> Dict[str, Any]:
    active = {}
    for key, val in full_glossary.items():
        keywords = extract_match_keywords(key)
        if any(kw in raw_text for kw in keywords):
            active[key] = val
    return active

def get_sliced_story_summary(full_summary: str, current_chap_num: float, window_size: int = 5) -> str:
    lines = full_summary.split('\n')
    header_lines = []
    
    for line in lines:
        line_stripped = line.strip()
        if line_stripped and re.match(r'^\[第\s*\d+(?:\.\d+)?\s*[話话]', line_stripped):
            break
        header_lines.append(line)
    header = "\n".join(header_lines).strip()
    
    parsed_chapters = []
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue
        match = re.match(r'^\[第\s*(\d+(?:\.\d+)?)\s*[話话]', line_stripped)
        if match:
            try:
                num = float(match.group(1))
                parsed_chapters.append((num, line_stripped))
            except ValueError:
                pass
                
    parsed_chapters.sort(key=lambda x: x[0])
    
    selected_chapters = []
    chap_1 = next((item for item in parsed_chapters if item[0] == 1.0), None)
    if chap_1:
        selected_chapters.append(chap_1)
        
    prior_chapters = [item for item in parsed_chapters if item[0] < current_chap_num and item[0] != 1.0]
    recent_chapters = prior_chapters[-window_size:] if prior_chapters else []
    selected_chapters.extend(recent_chapters)
    
    unique_dict = {}
    for num, line_content in selected_chapters:
        unique_dict[num] = line_content
        
    sorted_selected = sorted(unique_dict.items(), key=lambda x: x[0])
    
    result = header + "\n\n"
    if sorted_selected:
        result += "\n\n".join([item[1] for item in sorted_selected])
    else:
        result += "尚无符合条件的故事概要。"
    return result

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run local glossary and story-summary filtering diagnostics."
    )
    parser.add_argument(
        "--workspace",
        default=os.environ.get("TRANSLATOR_WORKSPACE"),
        help="Workspace containing Glossary.json, STORY_SUMMARY.md, and 生肉/.",
    )
    args = parser.parse_args(argv)
    if not args.workspace:
        parser.error("--workspace or TRANSLATOR_WORKSPACE is required.")

    workspace_dir = os.path.abspath(args.workspace)
    glossary_path = os.path.join(workspace_dir, "Glossary.json")
    summary_path = os.path.join(workspace_dir, "STORY_SUMMARY.md")
    glossary = load_glossary(glossary_path)
    with open(summary_path, "r", encoding="utf-8") as summary_file:
        story_summary = summary_file.read()

    raw_dirs = (
        os.path.join(workspace_dir, "生肉", "1.神んてらの世界"),
        os.path.join(workspace_dir, "生肉", "2.小学五年生"),
    )
    test_chapter_file = None
    for raw_dir, chapter_marker in zip(raw_dirs, ("第10", "第23")):
        if not os.path.exists(raw_dir):
            continue
        test_chapter_file = next(
            (
                os.path.join(raw_dir, filename)
                for filename in os.listdir(raw_dir)
                if chapter_marker in filename
            ),
            None,
        )
        if test_chapter_file:
            break

    if not test_chapter_file and os.path.exists(raw_dirs[0]):
        files = os.listdir(raw_dirs[0])
        if files:
            test_chapter_file = os.path.join(raw_dirs[0], files[0])

    if not test_chapter_file:
        print("No raw chapter file found for testing.")
        return 0

    with open(test_chapter_file, "r", encoding="utf-8") as chapter_file:
        raw_text = chapter_file.read()

    chap_num = extract_chapter_num(os.path.basename(test_chapter_file))
    print(f"Parsed chapter number: {chap_num}")

    filtered = filter_glossary(raw_text, glossary)
    print(f"Glossary Total Terms parsed: {len(glossary)}")
    print(f"Glossary Filtered Terms: {len(filtered)}")

    if chap_num is not None:
        sliced_summary = get_sliced_story_summary(story_summary, chap_num)
        print("Story Summary Sliced Length (chars):", len(sliced_summary))
        print("Original Story Summary Length (chars):", len(story_summary))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
