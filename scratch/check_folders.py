import os
WORKSPACE_DIR = r"d:\OWN\Programming\AI\TranslatorAI\祝福のネトラレラ_祝福的牛头人"

paths_to_check = [
    os.path.join(WORKSPACE_DIR, "生肉", "神んてらの世界"),
    os.path.join(WORKSPACE_DIR, "生肉", "1.神んてらの世界"),
    os.path.join(WORKSPACE_DIR, "熟肉", "神的世界"),
    os.path.join(WORKSPACE_DIR, "熟肉", "Ntera神的世界"),
]

for p in paths_to_check:
    print(f"Path: {p}")
    print(f"  Exists: {os.path.exists(p)}")
    if os.path.exists(p):
        print(f"  Is dir: {os.path.isdir(p)}")
        print(f"  Contents count: {len(os.listdir(p))}")
