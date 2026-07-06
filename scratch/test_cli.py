import os
import subprocess
import json
import re

prompt = "TASK: Say hello in JSON format {\"msg\": \"hello\"}. Output ONLY the result."
cmd = ["gemini", "-p", prompt, "-o", "json", "--approval-mode", "plan"]

# Test isolated CWD
temp_dir = os.path.join(os.getcwd(), "scratch", "cli_temp")
os.makedirs(temp_dir, exist_ok=True)

print(f"Running in {temp_dir}: {' '.join(cmd)}")
result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', shell=True, cwd=temp_dir)
print(f"Return code: {result.returncode}")
print(f"STDOUT:\n{result.stdout}")
print(f"STDERR:\n{result.stderr}")
