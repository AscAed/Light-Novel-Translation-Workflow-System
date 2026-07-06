import os
import sys
import json
import urllib.request

def get_embedding(text, base_url):
    # Call the mock embedding API
    url = f"{base_url}/gemini/embedContent"
    payload = {"model": "text-embedding-004", "contents": [text]}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("embedding", {}).get("values", [0.1] * 768)
    except Exception as e:
        print(f"Error fetching embedding: {e}")
        # Default fallback vector
        return [0.1] * 768

def main():
    # Read environment control parameters or use defaults
    workspace_dir = os.environ.get("TEST_WORKSPACE_DIR", ".")
    raw_dir = os.environ.get("TEST_RAW_DIR", os.path.join(workspace_dir, "生肉"))
    output_dir = os.environ.get("TEST_OUTPUT_DIR", os.path.join(workspace_dir, "熟肉"))
    tm_path = os.environ.get("TEST_TM_PATH", os.path.join(workspace_dir, "Knowledge", "translation_memory.json"))
    
    # Port configuration for mock API calls
    mock_port = os.environ.get("MOCK_SERVER_PORT", "6006")
    base_url = f"http://127.0.0.1:{mock_port}"

    print(f"Starting alignment tool. Raw: {raw_dir}, Output: {output_dir}")

    # Check if directories exist
    if not os.path.exists(raw_dir) or not os.path.exists(output_dir):
        print("Error: Raw or output directory does not exist.")
        sys.exit(1)

    # Scan raw files
    raw_files = [f for f in os.listdir(raw_dir) if f.endswith(".md")]
    tm_data = {"chapters": {}}

    for f in raw_files:
        raw_file_path = os.path.join(raw_dir, f)
        translated_file_path = os.path.join(output_dir, f)

        if not os.path.exists(translated_file_path):
            print(f"Skipping {f} (translation not found)")
            continue

        with open(raw_file_path, "r", encoding="utf-8") as file:
            raw_content = file.read()
        with open(translated_file_path, "r", encoding="utf-8") as file:
            translated_content = file.read()

        # Split into paragraphs, strip whitespace, ignore empty lines
        raw_paras = [p.strip() for p in raw_content.split("\n\n") if p.strip()]
        translated_paras = [p.strip() for p in translated_content.split("\n\n") if p.strip()]

        if len(raw_paras) != len(translated_paras):
            print(f"Error: Paragraph count mismatch in {f}. Raw: {len(raw_paras)}, Translated: {len(translated_paras)}")
            sys.exit(1)

        chapter_pairs = []
        for rp, tp in zip(raw_paras, translated_paras):
            vec = get_embedding(rp, base_url)
            chapter_pairs.append({
                "raw": rp,
                "translated": tp,
                "embedding": vec
            })

        tm_data["chapters"][f] = chapter_pairs
        print(f"Successfully aligned chapter {f} with {len(chapter_pairs)} paragraphs.")

    os.makedirs(os.path.dirname(tm_path), exist_ok=True)
    with open(tm_path, "w", encoding="utf-8") as out:
        json.dump(tm_data, out, ensure_ascii=False, indent=2)

    print(f"Alignment database written to {tm_path}")
    sys.exit(0)

if __name__ == "__main__":
    main()
