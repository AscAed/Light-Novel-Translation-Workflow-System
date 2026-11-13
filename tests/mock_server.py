import json
import http.server
import socketserver
import threading
import sys
import urllib.parse
import re

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


def _prompt_payload(prompt):
    match = re.search(r"```json\s*(.*?)\s*```", prompt, re.DOTALL)
    if not match:
        return []
    try:
        payload = json.loads(match.group(1))
        return payload if isinstance(payload, list) else []
    except json.JSONDecodeError:
        return []


def _mock_stage_response(prompt, stage, prefix=""):
    payload = _prompt_payload(prompt)
    if stage == "annotation":
        return {
            "annotated_paragraphs": [
                {
                    "paragraph": item.get("paragraph", ""),
                    "speaker": "旁白",
                    "context_hint": "",
                }
                for item in payload
                if isinstance(item, dict)
            ]
        }

    source_key = "paragraph" if stage == "translation" else "raw"
    target_key = {
        "translation": "translated_paragraphs",
        "proofread": "corrected_text",
        "polish": "polished_paragraphs",
    }[stage]
    result = []
    custom_translations = SERVER_STATE.get("custom_translations", {})
    for item in payload:
        if not isinstance(item, dict):
            continue
        source = item.get(source_key, "")
        current = item.get("translated", "")
        if stage == "translation":
            translated = next(
                (value for key, value in custom_translations.items() if key in source),
                f"{prefix}{source}",
            )
        elif stage == "proofread":
            translated = current.replace("【初译】", "【校对】")
        else:
            translated = current.replace("【校对】", "【润色】")
        result.append(translated)

    if stage == "translation" and SERVER_STATE.get("line_count_mismatch_active"):
        if len(result) > 1:
            result = result[:-1]
        else:
            result.append(f"{prefix}额外段落")
    if stage == "proofread" and SERVER_STATE.get("quote_mismatch_active") and result:
        result[0] += "「"
    return {target_key: result}


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

            if "请分析以下日文小说段落" in prompt:
                response_obj = _mock_stage_response(prompt, "annotation")
            elif "请检查以下段落翻译" in prompt:
                response_obj = _mock_stage_response(prompt, "proofread")
            elif "请润色以下翻译" in prompt:
                response_obj = _mock_stage_response(prompt, "polish")
            else:
                response_obj = _mock_stage_response(prompt, "translation", "【初译】")
            content_str = json.dumps(response_obj, ensure_ascii=False)

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

            # Determine response structure. If schema requires JSON (like initial or proofread fallback)
            # we should return valid JSON inside candidate text.
            response_schema = req_data.get("config", {}).get("response_schema")
            # Or in generateContentConfig
            if not response_schema and "config" in req_data:
                response_schema = req_data["config"].get("responseSchema")

            schema_text = json.dumps(response_schema, ensure_ascii=False)
            if "annotated_paragraphs" in schema_text:
                response_obj = _mock_stage_response(prompt, "annotation")
            elif "translated_paragraphs" in schema_text:
                response_obj = _mock_stage_response(prompt, "translation", "【Gemini初译】")
            elif "corrected_text" in schema_text:
                response_obj = _mock_stage_response(prompt, "proofread")
            elif "polished_paragraphs" in schema_text:
                response_obj = _mock_stage_response(prompt, "polish")
            else:
                response_obj = {"text": "【Gemini】mock response"}
            candidate_text = json.dumps(response_obj, ensure_ascii=False) if response_schema else str(response_obj)

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
