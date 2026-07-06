import os
import sys
import socket
import subprocess
import time
import urllib.request
import json

def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port

def wait_for_server(port, timeout=10):
    start = time.time()
    url = f"http://127.0.0.1:{port}/health"
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode('utf-8'))
                    if data.get("status") == "ok":
                        return True
        except Exception:
            pass
        time.sleep(0.2)
    return False

def main():
    os.environ["PYTHONUTF8"] = "1"
    print("==================================================")
    print("E2E Test Runner Starting...")
    print("==================================================")
    
    # 1. Find a free port for the mock server
    port = get_free_port()
    print(f"Allocated free port: {port}")
    
    # 2. Start the mock server in a background process
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    mock_server_script = os.path.join(project_root, "tests", "mock_server.py")
    
    print("Launching mock server...")
    server_proc = subprocess.Popen(
        [sys.executable, mock_server_script, str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    # 3. Wait for the mock server to be healthy
    print("Waiting for mock server to become healthy...")
    if not wait_for_server(port):
        print("Error: Mock server failed to start or check health in time.")
        server_proc.terminate()
        sys.exit(1)
    print("Mock server is healthy and ready.")
    
    # 4. Run the unittest suite
    test_script = os.path.join(project_root, "tests", "test_e2e.py")
    env = os.environ.copy()
    env["MOCK_SERVER_PORT"] = str(port)
    
    print("\nRunning E2E tests...")
    test_proc = subprocess.run(
        [sys.executable, "-m", "unittest", test_script],
        env=env
    )
    
    # 5. Clean up the mock server
    print("\nStopping mock server...")
    server_proc.terminate()
    try:
        server_proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        server_proc.kill()
        
    print("==================================================")
    print(f"Tests Completed. Exit code: {test_proc.returncode}")
    print("==================================================")
    
    sys.exit(test_proc.returncode)

if __name__ == "__main__":
    main()
