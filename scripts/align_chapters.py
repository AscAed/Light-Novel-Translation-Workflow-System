import logging
logger = logging.getLogger(__name__)
# scripts/align_chapters.py
# Paragraph alignment tool for compiling Translation Memory (TM) database.
# Compliant with Australian English spelling conventions.

import os
import sys
import logging
import json
import re
import math

# If running in a test context, dynamically mock the google-genai library
# so the script calls the local mock server instead of real API endpoints.
mock_port = os.environ.get("MOCK_SERVER_PORT")
if mock_port:
    import urllib.request
    
    class MockEmbedValues:
        def __init__(self, values):
            self.values = values

    class MockEmbedResponse:
        def __init__(self, embeddings):
            self.embeddings = embeddings

    class MockModels:
        def embed_content(self, model, contents):
            url = f"http://127.0.0.1:{mock_port}/gemini/embedContent"
            payload = {"model": model, "contents": contents}
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            timeout = float(os.environ.get("API_TIMEOUT", "10.0"))
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    val = res_data.get("embedding", {}).get("values", [0.1] * 768)
            except urllib.error.URLError as e:
                if isinstance(e.reason, TimeoutError):
                    logging.exception(f"Warning: Mock Gemini API request timed out after {timeout} seconds.")
                else:
                    logging.exception(f"Warning: Mock Gemini API request failed: {e}")
                val = [0.1] * 768
            except TimeoutError:
                logging.exception(f"Warning: Mock Gemini API request timed out after {timeout} seconds.")
                val = [0.1] * 768
            except Exception as e:
                logger.warning(f"Mock Gemini API request encountered an unexpected error: {e}", exc_info=True)
                val = [0.1] * 768
            return MockEmbedResponse([MockEmbedValues(val) for _ in contents])

    class MockClient:
        def __init__(self, api_key=None, http_options=None):
            self.models = MockModels()

    import types as pytypes
    google_module = pytypes.ModuleType("google")
    genai_module = pytypes.ModuleType("google.genai")
    genai_module.Client = MockClient
    google_module.genai = genai_module
    sys.modules["google"] = google_module
    sys.modules["google.genai"] = genai_module


TN_PATTERN = r'^\s*[\(（](?:译|注|T/N|翻译|意为|此处)[:：].*?[\)）]\s*$'


def is_translator_note(p: str) -> bool:
    """Check if the paragraph is a translator note using standard pattern."""
    return bool(re.match(TN_PATTERN, p))


def is_dialogue_anchor(p: str) -> bool:
    """Check if the paragraph begins and ends with quote markers."""
    p_stripped = p.strip()
    if not p_stripped:
        return False
    return (p_stripped.startswith('「') and p_stripped.endswith('」')) or \
           (p_stripped.startswith('『') and p_stripped.endswith('』'))


def get_anchor_type(p: str) -> str:
    """Retrieve the type of dialogue anchor for matching validation."""
    p_stripped = p.strip()
    if p_stripped.startswith('「') and p_stripped.endswith('」'):
        return "「」"
    if p_stripped.startswith('『') and p_stripped.endswith('』'):
        return "『』"
    return ""


def check_anchors_match(raw_paras: list[str], trans_paras: list[str]) -> bool:
    """Validate whether dialogue anchors match exactly in count and types."""
    raw_anchors = [p for p in raw_paras if is_dialogue_anchor(p)]
    trans_anchors = [p for p in trans_paras if is_dialogue_anchor(p)]
    if len(raw_anchors) != len(trans_anchors):
        return False
    for r, t in zip(raw_anchors, trans_anchors):
        if get_anchor_type(r) != get_anchor_type(t):
            return False
    return True


def align_narrative_block(raw_block: list[str], trans_block: list[str]) -> list[tuple[str, str]]:
    """Align a narrative sub-block using TN filtering and merging fallbacks."""
    if len(raw_block) == len(trans_block):
        return list(zip(raw_block, trans_block))

    # Tier 2: Standalone translator note filtering
    trans_filtered = [p for p in trans_block if not is_translator_note(p)]
    if len(raw_block) == len(trans_filtered):
        return list(zip(raw_block, trans_filtered))

    # Tier 3: Block merging fallback
    merged_raw = "\n\n".join(raw_block)
    merged_trans = "\n\n".join(trans_filtered)
    return [(merged_raw, merged_trans)]


def align_anchor_guided(raw_paras: list[str], trans_paras: list[str]) -> list[tuple[str, str]]:
    """Partition narrative blocks and align them using dialogue anchors."""
    raw_indices = [i for i, p in enumerate(raw_paras) if is_dialogue_anchor(p)]
    trans_indices = [j for j, p in enumerate(trans_paras) if is_dialogue_anchor(p)]

    # If no anchors are present and paragraph counts mismatch, raise error (Case 34)
    if not raw_indices and len(raw_paras) != len(trans_paras):
        raise ValueError("No dialogue anchors found and paragraph counts mismatch.")

    aligned_pairs = []
    r_start, t_start = 0, 0

    for r_idx, t_idx in zip(raw_indices, trans_indices):
        aligned_pairs.extend(align_narrative_block(raw_paras[r_start:r_idx], trans_paras[t_start:t_idx]))
        aligned_pairs.append((raw_paras[r_idx], trans_paras[t_idx]))
        r_start, t_start = r_idx + 1, t_idx + 1

    aligned_pairs.extend(align_narrative_block(raw_paras[r_start:], trans_paras[t_start:]))
    return aligned_pairs


def gc_cost(l1: int, l2: int, c: float = 1.2, s2: float = 6.8) -> float:
    """Compute the Gale-Church distance cost between two text lengths."""
    if l1 == 0 and l2 == 0:
        return 0.0
    denom = max(l1, 1) * c * s2
    delta = (l2 - l1 * c) / math.sqrt(denom)
    val = abs(delta) / 1.41421356
    try:
        prob = math.erfc(val)
        return -math.log(max(prob, 1e-100))
    except Exception:
        return 100.0


def gale_church_align(raw_paras: list[str], trans_paras: list[str]) -> list[tuple[str, str]]:
    """Apply Gale-Church DP paragraph alignment fallback."""
    n, m = len(raw_paras), len(trans_paras)
    dp = [[float("inf")] * (m + 1) for _ in range(n + 1)]
    backptr = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0

    priors = {
        (1, 1): -math.log(0.89),
        (1, 0): -math.log(0.0099),
        (0, 1): -math.log(0.0099),
        (1, 2): -math.log(0.089),
        (2, 1): -math.log(0.089),
        (2, 2): -math.log(0.011)
    }

    for i in range(n + 1):
        for j in range(m + 1):
            if i == 0 and j == 0:
                continue
            for (di, dj), prior in priors.items():
                if i - di >= 0 and j - dj >= 0:
                    r_len = sum(len(raw_paras[i - k - 1]) for k in range(di))
                    t_len = sum(len(trans_paras[j - k - 1]) for k in range(dj))
                    cost = gc_cost(r_len, t_len) + prior
                    val = dp[i - di][j - dj] + cost
                    if val < dp[i][j]:
                        dp[i][j] = val
                        backptr[i][j] = (di, dj)

    path = []
    i, j = n, m
    while i > 0 or j > 0:
        transition = backptr[i][j]
        if transition is None:
            break
        di, dj = transition
        path.append((i - di, i, j - dj, j))
        i -= di
        j -= dj
    path.reverse()

    aligned_pairs = []
    for r_start, r_end, t_start, t_end in path:
        r_txt = "\n\n".join(raw_paras[r_start:r_end])
        t_txt = "\n\n".join(trans_paras[t_start:t_end])
        aligned_pairs.append((r_txt, t_txt))
    return aligned_pairs


def align_chapter(raw_content: str, trans_content: str) -> list[tuple[str, str]]:
    """Determine alignment strategy and execute paragraph alignment."""
    raw_paras = [p.strip() for p in raw_content.split("\n\n") if p.strip()]
    trans_paras = [p.strip() for p in trans_content.split("\n\n") if p.strip()]

    if check_anchors_match(raw_paras, trans_paras):
        return align_anchor_guided(raw_paras, trans_paras)
    else:
        return gale_church_align(raw_paras, trans_paras)


def generate_embeddings_batched(texts: list[str], batch_size: int = 50) -> list[list[float]]:
    """Generate paragraph embeddings in batches to prevent rate limits."""
    from google import genai
    client = genai.Client(http_options={'timeout': float(os.environ.get("API_TIMEOUT", 10.0))})
    embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        response = client.models.embed_content(
            model="gemini-embedding-2",
            contents=batch
        )
        embeddings.extend([e.values for e in response.embeddings])
    return embeddings


def load_existing_tm(tm_path: str) -> dict:
    """Load the existing translation memory database if it exists."""
    if os.path.exists(tm_path):
        try:
            with open(tm_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "chapters" in data:
                    return data
        except Exception:
            pass
    return {"chapters": {}}


def save_tm(tm_path: str, tm_data: dict):
    """Save the updated translation memory database to disk."""
    os.makedirs(os.path.dirname(tm_path), exist_ok=True)
    with open(tm_path, "w", encoding="utf-8") as f:
        json.dump(tm_data, f, ensure_ascii=False, indent=2)


def main():
    """Initialise paths, scan files, run alignment and save TM database."""
    import argparse
    parser = argparse.ArgumentParser(description="LN Paragraph Alignment Tool")
    parser.add_argument("--project", "-p", type=str, help="Project name inside projects/ folder")
    parser.add_argument("--config", "-c", type=str, help="Path to config JSON file")
    args, _ = parser.parse_known_args()
    
    # Import Config to dynamically resolve paths based on project/config options
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from pipeline import Config
    Config.load_config(project=args.project, config_file=args.config)
    
    raw_dir = Config.RAW_DIR
    output_dir = Config.OUTPUT_DIR
    tm_path = Config.TM_PATH

    print(f"Starting alignment tool. Raw: {raw_dir}, Output: {output_dir}")
    if not os.path.exists(raw_dir) or not os.path.exists(output_dir):
        print("Error: Raw or output directory does not exist.")
        sys.exit(1)

    raw_files = [f for f in os.listdir(raw_dir) if f.endswith(".md")]
    def sort_key(filename):
        match = re.search(r'第(\d+)話', filename)
        return int(match.group(1)) if match else float('inf')
    raw_files = sorted(raw_files, key=sort_key)

    tm_data = load_existing_tm(tm_path)

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

        try:
            aligned_pairs = align_chapter(raw_content, translated_content)
        except Exception as e:
            logger.error(f"Error aligning chapter {f}: {e}", exc_info=True)
            sys.exit(1)

        # Filter out empty pairs to prevent database pollution
        valid_pairs = [(r, t) for r, t in aligned_pairs if r.strip() and t.strip()]

        # Generate embeddings in batches for the raw paragraphs
        raw_texts = [r for r, _ in valid_pairs]
        embeddings = generate_embeddings_batched(raw_texts)

        chapter_pairs = []
        for (r, t), embedding in zip(valid_pairs, embeddings):
            chapter_pairs.append({
                "raw": r,
                "translated": t,
                "embedding": embedding
            })

        tm_data["chapters"][f] = chapter_pairs
        print(f"Successfully aligned chapter {f} with {len(chapter_pairs)} paragraphs.")

    save_tm(tm_path, tm_data)
    print(f"Alignment database written to {tm_path}")
    sys.exit(0)


if __name__ == "__main__":
    main()
