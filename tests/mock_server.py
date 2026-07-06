import json
import http.server
import socketserver
import threading
import sys
import urllib.parse

# Global state for the mock server
SERVER_STATE = {
    "sakura_response_delay": 0.0,
    "deepseek_response_delay": 0.0,
    "sakura_offline": False,
    "deepseek_status_code": 200,
    "gemini_status_code": 200,
    "deepseek_safety_blocked": False,
    "gemini_safety_blocked": False,
    "line_count_mismatch_active": False,
    "quote_mismatch_active": False,
    "custom_translations": {},
    "embed_values": [0.1] * 768
}

class MockServerRequestHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress logging to keep output clean during tests
        pass

    def _send_json(self, data, status_code=200):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _send_error(self, status_code, message="Error"):
        self.send_response(status_code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(message.encode("utf-8"))

    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        if parsed_path.path == "/health":
            self._send_json({"status": "ok"})
        else:
            self._send_error(404, "Not Found")

    def do_POST(self):
        parsed_path = urllib.parse.urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)
        
        try:
            req_data = json.loads(post_data.decode("utf-8")) if post_data else {}
        except Exception:
            req_data = {}

        # Admin routes
        if parsed_path.path == "/set_state":
            SERVER_STATE.update(req_data)
            self._send_json({"status": "state updated", "state": SERVER_STATE})
            return

        if parsed_path.path == "/get_state":
            self._send_json(SERVER_STATE)
            return

        # Handle API routes
        # 1. OpenAI-compatible /v1/chat/completions (Sakura/DeepSeek/Coding Plan)
        if parsed_path.path == "/v1/chat/completions":
            # Simulate offline Sakura API
            if SERVER_STATE.get("sakura_offline"):
                # Force connection close without response
                self.close_connection = True
                return

            # Check status code override
            deepseek_status = SERVER_STATE.get("deepseek_status_code", 200)
            if deepseek_status != 200:
                self._send_error(deepseek_status, f"Simulated error {deepseek_status}")
                return

            messages = req_data.get("messages", [])
            model = req_data.get("model", "")
            
            # Extract last message prompt
            prompt = messages[-1].get("content", "") if messages else ""
            
            # Check safety block
            if SERVER_STATE.get("deepseek_safety_blocked"):
                # Simulating a safety block from DeepSeek / OpenAI compatible API
                # Typically, this returns a 400 or a completion with content filter finish reason
                self._send_json({
                    "id": "chatcmpl-mock",
                    "object": "chat.completion",
                    "created": 1234567,
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Content blocked due to safety guidelines."
                        },
                        "finish_reason": "content_filter"
                    }]
                })
                return

            # Check custom translations mapping
            translation_content = ""
            for key, val in SERVER_STATE.get("custom_translations", {}).items():
                if key in prompt:
                    translation_content = val
                    break

            if not translation_content:
                # Automatic mock behaviour based on prompt & model type
                if "qwen3.6-plus" in model or "initial" in model.lower() or "sakura" in model.lower():
                    # Initial translator
                    raw_text = ""
                    # Extract from [RAW_TEXT]:
                    if "[RAW_TEXT]:" in prompt:
                        raw_text = prompt.split("[RAW_TEXT]:")[-1].strip()
                    else:
                        raw_text = prompt
                    
                    lines = raw_text.split("\n")
                    translated_lines = []
                    for line in lines:
                        if not line.strip():
                            translated_lines.append("")
                            continue
                        # Basic translation translation simulation preserving quotes
                        translated = f"【初译】{line}"
                        translated_lines.append(translated)

                    if SERVER_STATE.get("line_count_mismatch_active"):
                        # Drop the last line to cause line count mismatch
                        if len(translated_lines) > 1:
                            translated_lines = translated_lines[:-1]
                        else:
                            translated_lines.append("【初译】Extra line")

                    raw_translation = "\n".join(translated_lines)
                    translation_content = json.dumps({"raw_translation": raw_translation}, ensure_ascii=False)

                elif "qwen3-max" in model or "proofread" in model.lower() or "logic" in model.lower() or "flash" in model.lower():
                    # Proofreader
                    raw_translation = ""
                    if "[RAW_TRANSLATION]:" in prompt:
                        raw_translation = prompt.split("[RAW_TRANSLATION]:")[-1].strip()
                    else:
                        raw_translation = prompt
                    
                    lines = raw_translation.split("\n")
                    fixed_lines = []
                    for line in lines:
                        if not line.strip():
                            fixed_lines.append("")
                            continue
                        fixed_lines.append(line.replace("【初译】", "【校对】"))

                    # Simulated quote mismatch logic
                    if SERVER_STATE.get("quote_mismatch_active"):
                        if fixed_lines:
                            fixed_lines[0] = fixed_lines[0] + "「" # Unmatched quote

                    logic_fixed_text = "\n".join(fixed_lines)
                    translation_content = json.dumps({
                        "logic_fixed_text": logic_fixed_text,
                        "fixed_errors": ["Fixed prefix"]
                    }, ensure_ascii=False)

                else:
                    # Polisher or other general model
                    logic_fixed_text = ""
                    if "[LOGIC_FIXED_TEXT]:" in prompt:
                        logic_fixed_text = prompt.split("[LOGIC_FIXED_TEXT]:")[-1].strip()
                    else:
                        logic_fixed_text = prompt

                    lines = logic_fixed_text.split("\n")
                    polished_lines = []
                    for line in lines:
                        if not line.strip():
                            polished_lines.append("")
                            continue
                        polished_lines.append(line.replace("【校对】", "【润色】"))
                    
                    final_text = "\n".join(polished_lines)
                    translation_content = final_text

            # Return OpenAI completions response
            # Note: For polisher, pipeline expects either string or JSON dict.
            # If response_format is json_object, we must return json.
            is_json_requested = req_data.get("response_format", {}).get("type") == "json_object"
            content_str = translation_content
            if is_json_requested and not content_str.startswith("{"):
                if "qwen3.6-plus" in model or "initial" in model.lower() or "sakura" in model.lower():
                    content_str = json.dumps({"raw_translation": content_str}, ensure_ascii=False)
                elif "qwen3-max" in model or "proofread" in model.lower() or "logic" in model.lower() or "flash" in model.lower():
                    content_str = json.dumps({"logic_fixed_text": content_str, "fixed_errors": []}, ensure_ascii=False)
                else:
                    content_str = json.dumps({"text": content_str}, ensure_ascii=False)

            self._send_json({
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "created": 1234567,
                "model": model,
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content_str
                    },
                    "finish_reason": "stop"
                }],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 100,
                    "total_tokens": 200,
                    "prompt_tokens_details": {
                        "cached_tokens": 40,
                        "cache_creation_input_tokens": 60
                    }
                }
            })
            return

        # 2. Gemini Chat Completions (simulate API generateContent)
        if parsed_path.path.endswith("/generateContent") or "generateContent" in parsed_path.path:
            gemini_status = SERVER_STATE.get("gemini_status_code", 200)
            if gemini_status != 200:
                self._send_error(gemini_status, f"Simulated Gemini error {gemini_status}")
                return

            if SERVER_STATE.get("gemini_safety_blocked"):
                # Safety blocked response structure
                self._send_json({
                    "candidates": [{
                        "finish_reason": "SAFETY",
                        "content": {
                            "role": "model",
                            "parts": []
                        }
                    }]
                })
                return

            # Extract user prompt
            contents = req_data.get("contents", [])
            prompt = ""
            if contents and isinstance(contents, list):
                parts = contents[0].get("parts", [])
                if parts:
                    prompt = parts[0].get("text", "")

            # Check custom translations
            translation_content = ""
            for key, val in SERVER_STATE.get("custom_translations", {}).items():
                if key in prompt:
                    translation_content = val
                    break

            if not translation_content:
                # Standard Gemini fallback translation simulation
                raw_text = prompt
                if "INPUT_DATA:" in prompt:
                    raw_text = prompt.split("INPUT_DATA:")[-1].split("TASK:")[0].strip()
                elif "[RAW_TEXT]:" in prompt:
                    raw_text = prompt.split("[RAW_TEXT]:")[-1].strip()

                lines = raw_text.split("\n")
                gemini_lines = []
                for line in lines:
                    if not line.strip():
                        gemini_lines.append("")
                        continue
                    gemini_lines.append(f"【Gemini】{line}")
                
                translation_content = "\n".join(gemini_lines)

            # Determine response structure. If schema requires JSON (like initial or proofread fallback)
            # we should return valid JSON inside candidate text.
            response_schema = req_data.get("config", {}).get("response_schema")
            # Or in generateContentConfig
            if not response_schema and "config" in req_data:
                response_schema = req_data["config"].get("responseSchema")

            candidate_text = translation_content
            # Check if JSON format requested
            if response_schema:
                # Return JSON object
                if "logic_fixed_text" in json.dumps(response_schema):
                    candidate_text = json.dumps({
                        "logic_fixed_text": f"【Gemini校对】{translation_content}",
                        "fixed_errors": []
                    }, ensure_ascii=False)
                elif "raw_translation" in json.dumps(response_schema):
                    candidate_text = json.dumps({
                        "raw_translation": f"【Gemini初译】{translation_content}"
                    }, ensure_ascii=False)

            self._send_json({
                "candidates": [{
                    "finish_reason": "STOP",
                    "content": {
                        "role": "model",
                        "parts": [{
                            "text": candidate_text
                        }]
                    }
                }]
            })
            return

        # 3. Gemini Embedding Endpoint
        if parsed_path.path.endswith("/embedContent") or "embedContent" in parsed_path.path:
            self._send_json({
                "embedding": {
                    "values": SERVER_STATE.get("embed_values", [0.1] * 768)
                }
            })
            return

        self._send_error(404, "Not Found")

def run_mock_server(port):
    handler = MockServerRequestHandler
    httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
    httpd.allow_reuse_address = True
    print(f"Mock server running on port {port}")
    httpd.serve_forever()

if __name__ == "__main__":
    port = 6006
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    run_mock_server(port)
