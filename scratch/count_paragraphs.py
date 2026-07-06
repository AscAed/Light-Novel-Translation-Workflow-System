import os

raw_dir = r"d:/OWN/Programming/AI/TranslatorAI/祝福のネトラレラ_祝福的牛头人/生肉/1.神んてらの世界"
trans_dir = r"d:/OWN/Programming/AI/TranslatorAI/祝福のネトラレラ_祝福的牛头人/熟肉/Ntera神的世界"
output_file = r"d:/OWN/Programming/AI/TranslatorAI/祝福のネトラレラ_祝福的牛头人/scratch/count_results.txt"

def count_paragraphs(file_path):
    if not os.path.exists(file_path):
        return -1
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    # Normalize line endings
    content = content.replace('\r\n', '\n')
    # Split by double newline
    paras = [p.strip() for p in content.split('\n\n') if p.strip()]
    return len(paras)

results = []
for i in range(1, 19):
    filename = f"第{i}話.md"
    raw_path = os.path.join(raw_dir, filename)
    trans_path = os.path.join(trans_dir, filename)
    
    raw_count = count_paragraphs(raw_path)
    trans_count = count_paragraphs(trans_path)
    
    results.append({
        "chapter": i,
        "raw_count": raw_count,
        "trans_count": trans_count,
        "match": raw_count == trans_count
    })

with open(output_file, 'w', encoding='utf-8') as f:
    f.write("Chapter | Raw Paragraphs | Translated Paragraphs | Match?\n")
    f.write("--------|----------------|-----------------------|--------\n")
    for r in results:
        match_str = "Yes" if r["match"] else "No"
        f.write(f"Ch {r['chapter']:2d}   | {r['raw_count']:14d} | {r['trans_count']:21d} | {match_str}\n")
    
    f.write("\n\nDetailed analysis of lines per file:\n")
    for r in results:
        f.write(f"Chapter {r['chapter']}:\n")
        filename = f"第{r['chapter']}話.md"
        raw_path = os.path.join(raw_dir, filename)
        trans_path = os.path.join(trans_dir, filename)
        if os.path.exists(raw_path) and os.path.exists(trans_path):
            with open(raw_path, 'r', encoding='utf-8') as fr:
                r_lines = len(fr.readlines())
            with open(trans_path, 'r', encoding='utf-8') as ft:
                t_lines = len(ft.readlines())
            f.write(f"  Raw total lines: {r_lines}\n")
            f.write(f"  Trans total lines: {t_lines}\n")
