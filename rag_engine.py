# rag_engine.py
# RAG retrieval module for translation memory, glossary, and guidelines.
# Compliant with Australian English spelling conventions.

import logging
import os

import logging
import json
import re
import numpy as np
from utils import extract_chapter_num
import logging
import urllib.error
from typing import List, Dict, Any, Optional, Tuple
from utils import extract_chapter_num

logger = logging.getLogger(__name__)


class RAGEngine:
    """RAGEngine handles similarity search, glossary parsing, and partitioned guidelines."""

    def __init__(self, tm_path: str, glossary_path: str, guidelines_path: str):
        """Initialise paths and load initial database contents from disk."""
        self.logger = logging.getLogger(__name__)

        self.tm_path = tm_path
        self.glossary_path = glossary_path
        self.guidelines_path = guidelines_path

        self._cached_cleaned_glossary = None

        # Initialise translation memory
        self.tm_data = {"chapters": {}}
        if os.path.exists(self.tm_path):
            try:
                with open(self.tm_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "chapters" in data:
                        self.tm_data = data
            except json.JSONDecodeError as e:
                self.logger.error(f"Failed to decode translation memory JSON file '{self.tm_path}': {e}", exc_info=True)
                raise
            except OSError as e:
                self.logger.error(f"Failed to read translation memory file '{self.tm_path}': {e}", exc_info=True)
                raise

        # Cache for translation memory vectors
        self._cached_tm_matrix = None
        self._cached_tm_norms = None
        self._cached_candidates = None

        # Initialise glossary raw content
        self.glossary_raw = ""
        if os.path.exists(self.glossary_path):
            try:
                with open(self.glossary_path, "r", encoding="utf-8") as f:
                    self.glossary_raw = f.read()
            except Exception as e:
                logger.warning(f"Failed to read glossary from {self.glossary_path}: {e}", exc_info=True)

        # Initialise guidelines raw content
        self.guidelines_raw = ""
        if os.path.exists(self.guidelines_path):
            try:
                with open(self.guidelines_path, "r", encoding="utf-8") as f:
                    self.guidelines_raw = f.read()
            except Exception as e:
                logger.warning(f"Failed to read guidelines from {self.guidelines_path}: {e}", exc_info=True)

    def _invalidate_cache(self) -> None:
        """Invalidate the translation memory vector cache."""
        self._cached_tm_matrix = None
        self._cached_tm_norms = None
        self._cached_candidates = None

    def _build_cache(self) -> None:
        """Build the vectorized translation memory cache."""
        candidates = []
        for chap_name, pairs in self.tm_data.get("chapters", {}).items():
            if not isinstance(pairs, list):
                continue
            for pair in pairs:
                if isinstance(pair, dict) and "raw" in pair and "translated" in pair:
                    emb = pair.get("embedding")
                    if emb and isinstance(emb, list) and len(emb) > 0:
                        candidates.append((pair["raw"], pair["translated"], emb))

        if not candidates:
            self._cached_tm_matrix = np.array([])
            self._cached_tm_norms = np.array([])
            self._cached_candidates = []
            return

        self._cached_candidates = candidates

        # Create matrix and precalculate norms
        self._cached_tm_matrix = np.array([emb for _, _, emb in candidates])
        self._cached_tm_norms = np.linalg.norm(self._cached_tm_matrix, axis=1)
        # Avoid division by zero
        self._cached_tm_norms[self._cached_tm_norms == 0] = 1e-9

    def _generate_embedding_sync(self, text: str) -> List[float]:
        """Generate embedding vector using Gemini Embedding 2 via mock or real API."""
        mock_port = os.environ.get("MOCK_SERVER_PORT")
        if mock_port:
            import urllib.request
            url = f"http://127.0.0.1:{mock_port}/gemini/embedContent"
            payload = {"model": "gemini-embedding-2", "contents": [text]}
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            try:
                with urllib.request.urlopen(req, timeout=float(os.environ.get("API_TIMEOUT", 10.0))) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    return res_data.get("embedding", {}).get("values", [0.1] * 768)
            except (TimeoutError, urllib.error.URLError) as e:
                logger.warning(f"Mock server request failed (timeout or URL error): {e}", exc_info=True)
                return [0.1] * 768
            except Exception as e:
                logger.warning(f"Mock server request failed with unexpected error: {e}", exc_info=True)
                return [0.1] * 768
        else:
            from google import genai
            client = genai.Client()
            response = client.models.embed_content(
                model="gemini-embedding-2",
                contents=[text]
            )
            return response.embeddings[0].values

    async def query_translation_memory(self, raw_text: str, top_k: int = 3) -> List[Dict[str, str]]:
        """Query translation memory using cosine similarity matching."""
        if not raw_text.strip():
            return []

        try:
            q_emb = self._generate_embedding_sync(raw_text)
        except Exception as e:
            logger.warning(f"Failed to generate embedding for query: {e}", exc_info=True)
            return []

        if self._cached_tm_matrix is None:
            self._build_cache()

        if len(self._cached_candidates) == 0:
            return []

        q_arr = np.array(q_emb)
        q_norm = np.linalg.norm(q_arr) or 1e-9

        sims = np.dot(self._cached_tm_matrix, q_arr) / (self._cached_tm_norms * q_norm)

        k = min(top_k, len(sims))
        if k < len(sims):
            top_k_idx = np.argpartition(sims, -k)[-k:]
            top_k_idx = top_k_idx[np.argsort(sims[top_k_idx])[::-1]]
        else:
            top_k_idx = np.argsort(sims)[::-1]

        results = []
        for idx in top_k_idx:
            raw, trans, _ = self._cached_candidates[idx]
            results.append({"raw": raw, "translated": trans})

        return results

    _GLOSSARY_COMMENT_PATTERN = re.compile(r"//.*")
    _GLOSSARY_KEY_CLEAN_PATTERN = re.compile(r"[\(\（\[\]\{\}].*?[\)\）\[\]\{\}]")
    _GLOSSARY_KEY_SPLIT_PATTERN = re.compile(r"/|／|\bor\b|,|，|、")
    _GLOSSARY_VAL_SPLIT_PATTERN = re.compile(r"[/／\(\)（）]")
    _GUIDELINES_SPLIT_PATTERN = re.compile(r"(《翻译指导原则》\s*-\s*\[(?:全局通用|第\s*\d+(?:\.\d+)?\s*章)\])")
    _GUIDELINES_CHAP_PATTERN = re.compile(r"第\s*(\d+(?:\.\d+)?)\s*章")

    def _parse_glossary_json(self) -> dict:
        """Parse raw glossary JSON while removing single-line comments."""
        if not self.glossary_raw:
            return {}
        clean_content = self._GLOSSARY_COMMENT_PATTERN.sub("", self.glossary_raw)
        decoder = json.JSONDecoder()
        pos = 0
        merged = {}
        clean_content = clean_content.strip()
        while pos < len(clean_content):
            start = clean_content.find("{", pos)
            if start == -1:
                break
            try:
                # Pass the string and start index directly to avoid O(N) string slicing
                obj, idx = decoder.raw_decode(clean_content, start)
                if isinstance(obj, dict):
                    merged.update(obj)
                pos = idx
            except json.JSONDecodeError:
                pos = start + 1
        return merged

    def _get_precomputed_glossary(self) -> List[Dict[str, Any]]:
        if self._cached_cleaned_glossary is not None:
            return self._cached_cleaned_glossary

        merged = self._parse_glossary_json()
        precomputed = []
        for key, val in merged.items():
            clean_k = self._GLOSSARY_KEY_CLEAN_PATTERN.sub("", key).strip()
            raw_keywords = self._GLOSSARY_KEY_SPLIT_PATTERN.split(clean_k)
            keywords = [kw.strip() for kw in raw_keywords if kw.strip()]
            if not keywords:
                continue

            src = keywords[0]
            parts_v = self._GLOSSARY_VAL_SPLIT_PATTERN.split(str(val))
            dst_candidates = [item.strip() for item in parts_v if item.strip()]
            dst = dst_candidates[0] if dst_candidates else str(val).strip()

            precomputed.append({
                "keywords": keywords,
                "src": src,
                "dst": dst,
                "info": str(val).strip()
            })

        self._cached_cleaned_glossary = precomputed
        return precomputed

    def get_cleaned_glossary(self, raw_text: str) -> List[Dict[str, str]]:
        """Filter and return cleaned terminology mapping matching the raw text."""
        precomputed = self._get_precomputed_glossary()
        results = []
        for item in precomputed:
            if any(kw in raw_text for kw in item["keywords"]):
                results.append({
                    "src": item["src"],
                    "dst": item["dst"],
                    "info": item["info"]
                })
        return results

    def _parse_guidelines_content(self) -> Tuple[str, Dict[float, str]]:
        """Parse guidelines text into global rules and chapter-specific mappings."""
        if not self.guidelines_raw:
            return "", {}
        parts = self._GUIDELINES_SPLIT_PATTERN.split(self.guidelines_raw)
        global_parts = []
        chapter_dict = {}
        first_part = parts[0].strip()
        if first_part:
            global_parts.append(first_part)
        for i in range(1, len(parts), 2):
            header = parts[i]
            content = parts[i+1].strip() if i+1 < len(parts) else ""
            if "全局通用" in header:
                global_parts.append(content)
            else:
                match = self._GUIDELINES_CHAP_PATTERN.search(header)
                if match:
                    chapter_dict[float(match.group(1))] = content
        return "\n\n".join(global_parts).strip(), chapter_dict

    def _load_current_chapter_raw(self, chapter_filename: str) -> str:
        """Attempt to read raw chapter text from expected locations."""
        chapter_filename = os.path.basename(chapter_filename)
        base_dir = os.path.dirname(os.path.dirname(self.guidelines_path))
        clean_filename = os.path.basename(chapter_filename)
        paths_to_try = [
            os.path.join(base_dir, "生肉", clean_filename),
            os.path.join(base_dir, "生肉", "1.神んてらの世界", clean_filename),
            os.path.join(os.getcwd(), "生肉", clean_filename),
            os.path.join(os.getcwd(), "生肉", "1.神んてらの世界", clean_filename),
        ]
        for p in paths_to_try:
            if os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        return f.read()
                except Exception as e:
                    logger.warning(f"Failed to read raw chapter from {p}: {e}", exc_info=True)
                    pass
        return ""

    def _find_tm_filename(self, chap_num: float) -> Optional[str]:
        """Find the filename matching chapter number in translation memory."""
        for fn in self.tm_data.get("chapters", {}):
            if extract_chapter_num(fn, default=0.0) == chap_num:
                return fn
        return None

    def _get_chapter_tm_embedding(self, filename: str) -> Optional[np.ndarray]:
        """Compute the average paragraph embedding for chapter in TM."""
        if not hasattr(self, '_chapter_tm_embeddings_cache'):
            self._chapter_tm_embeddings_cache = {}
        if filename in self._chapter_tm_embeddings_cache:
            return self._chapter_tm_embeddings_cache[filename]

        pairs = self.tm_data.get("chapters", {}).get(filename, [])
        vectors = []
        for pair in pairs:
            emb = pair.get("embedding")
            if emb and isinstance(emb, list) and len(emb) > 0:
                vectors.append(emb)
        result = np.mean(vectors, axis=0) if vectors else None
        self._chapter_tm_embeddings_cache[filename] = result
        return result

    def _find_best_semantic_match(self, curr_emb: np.ndarray, candidates: list) -> Optional[float]:
        """Compare current chapter embedding with candidates and select highest similarity."""
        best_sim = -1.0
        best_chap = None
        for num in candidates:
            fn = self._find_tm_filename(num)
            if not fn:
                continue
            cand_emb = self._get_chapter_tm_embedding(fn)
            if cand_emb is None:
                continue
            sim = np.dot(curr_emb, cand_emb) / (np.linalg.norm(curr_emb) * np.linalg.norm(cand_emb))
            if sim > best_sim:
                best_sim = sim
                best_chap = num
        return best_chap

    def _semantic_fallback(self, target_chap: float, chapter_dict: dict, chapter_filename: str) -> str:
        """Perform semantic similarity fallback matching among adjacent chapters."""
        if not chapter_dict:
            return ""
        candidates = [num for num in [target_chap - 1, target_chap - 2, target_chap + 1, target_chap + 2] if num in chapter_dict]
        if not candidates:
            closest_num = min(chapter_dict.keys(), key=lambda k: abs(k - target_chap))
            return chapter_dict[closest_num]
        try:
            curr_text = self._load_current_chapter_raw(chapter_filename)
            paras = [p.strip() for p in curr_text.split("\n\n") if p.strip()][:3]
            if paras:
                curr_embs = [self._generate_embedding_sync(p) for p in paras]
                curr_emb = np.mean(curr_embs, axis=0)
                best_chap = self._find_best_semantic_match(curr_emb, candidates)
                if best_chap is not None:
                    return chapter_dict[best_chap]
        except Exception as e:
            logger.warning(f"Semantic fallback failed for chapter {chapter_filename}: {e}", exc_info=True)
            pass
        closest_num = min(candidates, key=lambda k: abs(k - target_chap))
        return chapter_dict[closest_num]

    def get_partitioned_guidelines(self, chapter_filename: str) -> str:
        """Retrieve global and matching/semantic-fallback chapter guidelines under 10KB."""
        global_guidelines, chapter_dict = self._parse_guidelines_content()
        target_chap = extract_chapter_num(chapter_filename, default=0.0)

        if target_chap in chapter_dict:
            matched_content = chapter_dict[target_chap]
        else:
            matched_content = self._semantic_fallback(target_chap, chapter_dict, chapter_filename)

        combined = f"{global_guidelines}\n\n{matched_content}".strip()

        # Constrain combined size to <10KB (using 9500 bytes to ensure safety margin)
        max_bytes = 9500
        combined_bytes = combined.encode("utf-8")
        if len(combined_bytes) > max_bytes:
            truncated = combined_bytes[:max_bytes].decode("utf-8", errors="ignore")
            combined = truncated + "\n... [Truncated due to length limit]"

        return combined

    def update_translation_memory(self, chapter_filename: str, paragraph_pairs: List[Dict[str, Any]]):
        """Append paragraph pairs with embedding vectors and persist updated database."""
        new_pairs = []
        for pair in paragraph_pairs:
            raw_text = pair.get("raw", "")
            translated_text = pair.get("translated", "")
            if not raw_text.strip() or not translated_text.strip():
                continue
            embedding = pair.get("embedding")
            if not embedding:
                try:
                    embedding = self._generate_embedding_sync(raw_text)
                except Exception as e:
                    logger.warning(f"Failed to generate embedding for raw text: {e}", exc_info=True)
                    embedding = [0.1] * 768
            new_pairs.append({
                "raw": raw_text,
                "translated": translated_text,
                "embedding": embedding
            })

        self.tm_data.setdefault("chapters", {})[chapter_filename] = new_pairs
        if hasattr(self, '_chapter_tm_embeddings_cache') and chapter_filename in self._chapter_tm_embeddings_cache:
            del self._chapter_tm_embeddings_cache[chapter_filename]

        # Invalidate the cache since tm_data has been mutated
        self._invalidate_cache()

        try:
            os.makedirs(os.path.dirname(self.tm_path), exist_ok=True)
            with open(self.tm_path, "w", encoding="utf-8") as f:
                json.dump(self.tm_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to write translation memory to {self.tm_path}: {e}", exc_info=True)
