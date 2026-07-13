import sys
import os
import logging
import json
import urllib.request

def main():
    # Parse arguments
    prompt = ""
    model = "auto"
    
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "-p" and i + 1 < len(args):
            prompt = args[i+1]
            i += 2
        elif args[i] == "-m" and i + 1 < len(args):
            model = args[i+1]
            i += 2
        else:
            i += 1

    # Port configuration
    mock_port = os.environ.get("MOCK_SERVER_PORT", "6006")
    url = f"http://127.0.0.1:{mock_port}/gemini/generateContent"

    # In CLI mode, prompt is built with:
    # "TASK: Follow the system instructions below to process the input.\n\nSYSTEM_INSTRUCTIONS:\n...\n\nINPUT_DATA:\n...\n\n"
    # We serialize this to match mock server generateContent expectations
    payload = {
        "model": model,
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ],
        "config": {}
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=float(os.environ.get("API_TIMEOUT", 10.0))) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            
            # Extract candidate text
            candidates = data.get("candidates", [])
            text_out = ""
            if candidates and candidates[0].get("content", {}).get("parts"):
                text_out = candidates[0]["content"]["parts"][0].get("text", "")
            
            # CLI output format expected by pipeline: JSON with "response" key
            out_obj = {"response": text_out}
            print(json.dumps(out_obj, ensure_ascii=False))
            sys.exit(0)
    except Exception as e:
        logging.exception(f"Gemini CLI mock error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
