# rag_engine.py
# RAG retrieval module for translation memory, glossary, and guidelines.
# Compliant with Australian English spelling conventions.

import logging
import os
import json
import re
import hashlib
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from embedding_provider import (
    embedding_identity_for_vector,
    generate_embeddings,
    is_compatible_embedding,
)
from utils import (
    extract_chapter_num,
    open_regular_file,
    parse_api_timeout,
    parse_provider_data_policy,
    reject_knowledge_draft_path,
    read_child_text,
    require_provider_data_authorized,
    validate_tm_source_provenance,
    write_bytes_atomically,
)
from scripts.validate_knowledge_provenance import audit_knowledge_provenance
from tm_review import load_reviewed_tm_snapshot

logger = logging.getLogger(__name__)
_KNOWLEDGE_REVIEW_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_EXPECTED_TM_HASH_UNSET = object()
_BOOK_BUNDLE_FIELDS = frozenset(
    {
        "source_snapshot_id",
        "ai_bundle_id",
        "bundle_set_relative_path",
        "bundle_set_sha256",
        "ai_bundle_relative_path",
        "ai_bundle_sha256",
        "episode_count",
    }
)


def _glossary_aliases(key: str) -> list[str]:
    clean_key = re.sub(r"[\(\（\[\]\{\}].*?[\)\）\[\]\{\}]", "", key).strip()
    raw_aliases = re.split(r"/|／|\bor\b|,|，|、", clean_key)
    return [alias.strip() for alias in raw_aliases if alias.strip()]


def _glossary_destination(value: Any) -> str:
    parts = re.split(r"[/／\(\)（）]", str(value))
    candidates = [part.strip() for part in parts if part.strip()]
    return candidates[0] if candidates else str(value).strip()


class RAGEngine:
    """RAGEngine handles similarity search, glossary parsing, and partitioned guidelines."""

    def __init__(
        self,
        tm_path: str,
        glossary_path: str,
        guidelines_path: str,
        api_timeout: Optional[float] = None,
        provider_data_policy=None,
        source_root: Optional[str] = None,
        source_manifest_path: Optional[str] = None,
        reviewed_tm_path: Optional[str] = None,
        translation_root: Optional[str] = None,
        allow_unreviewed_tm: bool = False,
        require_reviewed_glossary: bool = False,
        expected_book_bundle: Optional[dict] = None,
        require_full_book_coverage: bool = False,
        source_input_root: Optional[str] = None,
        source_input_map: Optional[dict] = None,
        reviewed_tm_translation_root: Optional[str] = None,
    ):
        """Initialise paths and load initial database contents from disk."""
        self.logger = logging.getLogger(__name__)

        if not isinstance(allow_unreviewed_tm, bool):
            raise ValueError("allow_unreviewed_tm must be a boolean.")
        if not isinstance(require_reviewed_glossary, bool):
            raise ValueError("require_reviewed_glossary must be a boolean.")
        if not isinstance(require_full_book_coverage, bool):
            raise ValueError("require_full_book_coverage must be a boolean.")
        if expected_book_bundle is not None and not isinstance(
            expected_book_bundle, dict
        ):
            raise ValueError("expected_book_bundle must be an object.")
        self.tm_path = tm_path
        self.glossary_path = glossary_path
        self.guidelines_path = guidelines_path
        self.source_root = source_root
        self.source_manifest_path = source_manifest_path
        self.reviewed_tm_path = reviewed_tm_path
        self.translation_root = translation_root
        self.reviewed_tm_translation_root = (
            translation_root
            if reviewed_tm_translation_root is None
            else reviewed_tm_translation_root
        )
        self.allow_unreviewed_tm = allow_unreviewed_tm
        self.require_reviewed_glossary = require_reviewed_glossary
        self.expected_book_bundle = expected_book_bundle
        self.require_full_book_coverage = require_full_book_coverage
        self.source_input_root = source_input_root
        self.source_input_map = source_input_map
        reject_knowledge_draft_path(self.glossary_path, "glossary input")
        self.api_timeout = parse_api_timeout(
            api_timeout if api_timeout is not None else os.environ.get("API_TIMEOUT", 10.0)
        )
        self.provider_data_policy = parse_provider_data_policy(
            provider_data_policy
            if provider_data_policy is not None
            else os.environ.get("PROVIDER_DATA_POLICY", {})
        )

        # Initialise translation memory
        self.tm_data = {"chapters": {}}
        self._tm_disk_sha256 = None
        self.reload_translation_memory()
        self._reviewed_tm_data = None
        if self.reviewed_tm_path:
            self._reviewed_tm_data = load_reviewed_tm_snapshot(
                self.reviewed_tm_path,
                self.source_root,
                self.reviewed_tm_translation_root,
                self.source_manifest_path,
                source_input_root=self.source_input_root,
                source_input_map=self.source_input_map,
            )

        # Initialise glossary raw content
        self.glossary_raw = ""
        if self.require_reviewed_glossary:
            try:
                with open_regular_file(self.glossary_path) as f:
                    self.glossary_raw = f.read()
            except (OSError, ValueError):
                raise ValueError(
                    "Project translation requires a readable reviewed glossary bundle."
                ) from None
            try:
                reviewed_glossary = json.loads(self.glossary_raw)
            except json.JSONDecodeError:
                raise ValueError(
                    "Project translation requires a valid reviewed glossary bundle."
                ) from None
            if (
                not isinstance(reviewed_glossary, dict)
                or "_knowledge_review_schema" not in reviewed_glossary
            ):
                raise ValueError(
                    "Project translation requires a reviewed glossary bundle."
                )
            self._parse_reviewed_glossary_bundle(reviewed_glossary)
        elif os.path.exists(self.glossary_path):
            try:
                with open(self.glossary_path, "r", encoding="utf-8") as f:
                    self.glossary_raw = f.read()
            except Exception as e:
                logger.warning(f"Failed to read glossary from {self.glossary_path}: {e}")

        # Initialise guidelines raw content
        self.guidelines_raw = ""
        if os.path.exists(self.guidelines_path):
            try:
                with open(self.guidelines_path, "r", encoding="utf-8") as f:
                    self.guidelines_raw = f.read()
            except Exception as e:
                logger.warning(f"Failed to read guidelines from {self.guidelines_path}: {e}")

    def _generate_embedding_sync(self, text: str) -> List[float]:
        """Generate embedding vector using Gemini Embedding 2 via mock or real API."""
        vectors, _ = generate_embeddings(
            [text],
            batch_size=1,
            api_timeout=self.api_timeout,
            provider_data_policy=self.provider_data_policy,
            require_api_key=True,
        )
        return vectors[0]

    @property
    def tm_retrieval_data(self) -> dict:
        if self._reviewed_tm_data is not None:
            return self._reviewed_tm_data
        if self.allow_unreviewed_tm:
            return self.tm_data
        return {"chapters": {}}

    async def query_translation_memory(self, raw_text: str, top_k: int = 3) -> List[Dict[str, str]]:
        """Query translation memory using cosine similarity matching."""
        if not raw_text.strip():
            return []

        candidates = []
        for chap_name, pairs in self.tm_retrieval_data.get("chapters", {}).items():
            if not isinstance(pairs, list):
                continue
            for pair in pairs:
                if isinstance(pair, dict) and "raw" in pair and "translated" in pair:
                    emb = pair.get("embedding")
                    identity = pair.get("embedding_identity")
                    if is_compatible_embedding(emb, identity):
                        candidates.append(
                            (pair["raw"], pair["translated"], emb, identity)
                        )

        if not candidates:
            return []

        try:
            q_emb = self._generate_embedding_sync(raw_text)
        except Exception as e:
            logger.warning(
                "Failed to generate embedding for query (%s).",
                type(e).__name__,
            )
            raise RuntimeError(
                "Translation-memory embedding failed; the chapter was not processed."
            ) from None

        q_arr = np.array(q_emb)
        q_norm = np.linalg.norm(q_arr) or 1e-9

        query_identity = embedding_identity_for_vector(q_emb)
        scores = []
        for raw, trans, emb, identity in candidates:
            if identity != query_identity:
                continue
            c_arr = np.array(emb)
            c_norm = np.linalg.norm(c_arr) or 1e-9
            sim = np.dot(q_arr, c_arr) / (q_norm * c_norm)
            scores.append((sim, raw, trans))

        scores.sort(key=lambda x: x[0], reverse=True)
        return [{"raw": raw, "translated": trans} for _, raw, trans in scores[:top_k]]

    def _parse_glossary_json(self) -> dict:
        """Parse raw glossary JSON while removing single-line comments."""
        if not self.glossary_raw:
            return {}
        try:
            parsed = json.loads(self.glossary_raw)
        except json.JSONDecodeError:
            if re.search(
                r'"_knowledge_review_schema"\s*:',
                self.glossary_raw,
            ):
                raise ValueError(
                    "Reviewed glossary bundle is malformed."
                ) from None
            parsed = None
        if isinstance(parsed, dict):
            if "_knowledge_review_schema" in parsed:
                return self._parse_reviewed_glossary_bundle(parsed)
            return parsed

        clean_content = re.sub(r"//.*", "", self.glossary_raw)
        decoder = json.JSONDecoder()
        pos = 0
        merged = {}
        clean_content = clean_content.strip()
        while pos < len(clean_content):
            start = clean_content.find("{", pos)
            if start == -1:
                break
            try:
                obj, idx = decoder.raw_decode(clean_content[start:])
                if isinstance(obj, dict):
                    merged.update(obj)
                pos = start + idx
            except json.JSONDecodeError:
                pos = start + 1
        return merged

    def _parse_reviewed_glossary_bundle(
        self,
        bundle: dict,
        *,
        allow_chapter_local_coverage: bool = False,
    ) -> dict:
        if not isinstance(allow_chapter_local_coverage, bool):
            raise ValueError("allow_chapter_local_coverage must be a boolean.")
        if (
            bundle.get("_knowledge_review_schema") != 1
            or isinstance(bundle.get("_knowledge_review_schema"), bool)
            or bundle.get("artifact_status") != "complete"
            or bundle.get("approval_status") != "approved_terms_only"
        ):
            raise ValueError("Reviewed glossary bundle has an invalid status.")

        terms = bundle.get("terms")
        review = bundle.get("review")
        if (
            not isinstance(terms, dict)
            or not terms
            or any(
                not isinstance(source, str)
                or not source
                or not isinstance(translation, str)
                or not translation
                for source, translation in terms.items()
            )
            or not isinstance(review, dict)
        ):
            raise ValueError("Reviewed glossary bundle has invalid terms or review.")

        hash_fields = (
            "candidate_glossary_sha256",
            "candidate_provenance_sha256",
            "review_receipt_sha256",
            "terms_sha256",
        )
        if any(
            not isinstance(review.get(field), str)
            or not _KNOWLEDGE_REVIEW_SHA256.fullmatch(review[field])
            for field in hash_fields
        ):
            raise ValueError("Reviewed glossary bundle has invalid hash bindings.")

        reviewer = review.get("reviewer")
        required_reviewer_fields = {"provider_id", "model_id", "review_id"}
        if (
            not isinstance(reviewer, dict)
            or not required_reviewer_fields <= set(reviewer)
            or any(
                not isinstance(reviewer[field], str) or not reviewer[field]
                for field in required_reviewer_fields
            )
        ):
            raise ValueError("Reviewed glossary bundle has no reviewer record.")

        decisions = review.get("decisions")
        if not isinstance(decisions, list):
            raise ValueError("Reviewed glossary bundle has no term decisions.")
        approved_sources = []
        for decision in decisions:
            decision_status = (
                decision.get("decision")
                if isinstance(decision, dict)
                else None
            )
            if (
                not isinstance(decision, dict)
                or not isinstance(decision.get("src"), str)
                or not isinstance(decision_status, str)
                or decision_status not in {"approved", "rejected", "escalated"}
                or not isinstance(decision.get("rationale"), str)
                or not decision["rationale"].strip()
                or not isinstance(decision.get("evidence"), list)
            ):
                raise ValueError("Reviewed glossary bundle has a malformed decision.")
            if decision_status == "approved":
                if not decision["evidence"]:
                    raise ValueError(
                        "Approved glossary term has no source evidence."
                    )
                approved_sources.append(decision["src"])

        if (
            len(approved_sources) != len(set(approved_sources))
            or set(approved_sources) != set(terms)
        ):
            raise ValueError(
                "Reviewed glossary terms do not match approved decisions."
            )
        canonical_terms = json.dumps(
            terms,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if hashlib.sha256(canonical_terms).hexdigest() != review["terms_sha256"]:
            raise ValueError("Reviewed glossary term hash does not match.")
        source_files = review.get("source_files")
        if (
            not self.source_root
            or not self.source_manifest_path
            or not isinstance(source_files, list)
            or not source_files
        ):
            raise ValueError(
                "Reviewed glossary requires a source root and manifest."
            )
        coverage = review.get("input_coverage")
        full_book_coverage = (
            isinstance(coverage, dict)
            and coverage.get("scope") == "all_configured_chapters"
        )
        chapter_local_coverage = (
            isinstance(coverage, dict)
            and coverage.get("scope") == "selected_chapter"
        )
        if allow_chapter_local_coverage:
            configured_count = (
                coverage.get("configured_chapter_count")
                if isinstance(coverage, dict)
                else None
            )
            included_count = (
                coverage.get("included_chapter_count")
                if isinstance(coverage, dict)
                else None
            )
            if (
                not chapter_local_coverage
                or coverage.get("complete_for_configured_chapters") is not False
                or isinstance(configured_count, bool)
                or configured_count != 1
                or isinstance(included_count, bool)
                or included_count != 1
                or len(source_files) != 1
            ):
                raise ValueError(
                    "Reviewed glossary lacks valid selected-chapter coverage."
                )
        elif self.require_full_book_coverage or full_book_coverage:
            configured_count = (
                coverage.get("configured_chapter_count")
                if isinstance(coverage, dict)
                else None
            )
            included_count = (
                coverage.get("included_chapter_count")
                if isinstance(coverage, dict)
                else None
            )
            if (
                not isinstance(coverage, dict)
                or coverage.get("scope") != "all_configured_chapters"
                or coverage.get("complete_for_configured_chapters") is not True
                or isinstance(configured_count, bool)
                or not isinstance(configured_count, int)
                or configured_count != len(source_files)
                or isinstance(included_count, bool)
                or not isinstance(included_count, int)
                or included_count != len(source_files)
                or not isinstance(self.source_input_root, str)
                or not self.source_input_root
                or not isinstance(self.source_input_map, dict)
                or set(self.source_input_map)
                != {
                    item.get("filename")
                    for item in source_files
                    if isinstance(item, dict)
                }
            ):
                raise ValueError(
                    "Reviewed glossary lacks complete coverage of the current "
                    "AI chapter map."
                )

        book_bundle = review.get("book_bundle")
        if book_bundle is not None:
            if (
                not isinstance(book_bundle, dict)
                or set(book_bundle) != _BOOK_BUNDLE_FIELDS
                or any(
                    not isinstance(book_bundle.get(field), str)
                    or not _KNOWLEDGE_REVIEW_SHA256.fullmatch(book_bundle[field])
                    for field in ("bundle_set_sha256", "ai_bundle_sha256")
                )
                or not isinstance(book_bundle.get("source_snapshot_id"), str)
                or not re.fullmatch(
                    r"source-v1-[0-9a-f]{64}",
                    book_bundle["source_snapshot_id"],
                )
                or not isinstance(book_bundle.get("ai_bundle_id"), str)
                or not re.fullmatch(
                    r"ai-v1-[0-9a-f]{64}",
                    book_bundle["ai_bundle_id"],
                )
                or any(
                    not isinstance(book_bundle.get(field), str)
                    or len(book_bundle[field]) > 4096
                    or "\\" in book_bundle[field]
                    or book_bundle[field].startswith("/")
                    or any(
                        part in {"", ".", ".."}
                        for part in book_bundle[field].split("/")
                    )
                    for field in (
                        "bundle_set_relative_path",
                        "ai_bundle_relative_path",
                    )
                )
                or isinstance(book_bundle.get("episode_count"), bool)
                or not isinstance(book_bundle.get("episode_count"), int)
                or (
                    book_bundle["episode_count"] != len(source_files)
                    if (
                        self.require_full_book_coverage
                        and not allow_chapter_local_coverage
                    )
                    or full_book_coverage
                    else book_bundle["episode_count"] < len(source_files)
                )
            ):
                raise ValueError(
                    "Reviewed glossary has malformed book bundle identity."
                )
        if self.require_full_book_coverage and (
            self.expected_book_bundle is None or book_bundle is None
        ):
            raise ValueError(
                "Reviewed glossary requires a current AI book bundle identity."
            )
        if self.expected_book_bundle is not None:
            if (
                book_bundle is None
                or set(self.expected_book_bundle) != _BOOK_BUNDLE_FIELDS
                or book_bundle != self.expected_book_bundle
            ):
                raise ValueError(
                    "Reviewed glossary belongs to a different AI book bundle."
                )
        findings = audit_knowledge_provenance(
            {
                "schema_version": 1,
                "artifact_status": "complete",
                "source_files": source_files,
            },
            self.source_root,
            self.source_manifest_path,
            source_input_root=self.source_input_root,
            source_input_map=self.source_input_map,
        )
        if not findings or any(item["status"] != "verified" for item in findings):
            raise ValueError("Reviewed glossary source versions are not current.")
        return terms

    def get_cleaned_glossary(
        self,
        raw_text: str,
        additional_glossary: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, str]]:
        """Filter and return cleaned terminology mapping matching the raw text."""
        entries = [
            (key, value, False)
            for key, value in self._parse_glossary_json().items()
        ]
        if additional_glossary is not None:
            if not isinstance(additional_glossary, dict):
                raise ValueError("Additional glossary must be a JSON object.")
            for source, translation in additional_glossary.items():
                if (
                    not isinstance(source, str)
                    or not source
                    or not isinstance(translation, str)
                    or not translation
                ):
                    raise ValueError("Additional glossary contains an invalid term.")
                existing_values = [
                    value for key, value, _ in entries if key == source
                ]
                if any(
                    _glossary_destination(value)
                    != _glossary_destination(translation)
                    for value in existing_values
                ):
                    raise ValueError(
                        "Reviewed global and chapter glossaries conflict."
                    )
                entries.append((source, translation, True))

        results = []
        destinations_by_alias = {}
        aliases_with_additional_terms = set()
        for key, val, is_additional in entries:
            keywords = _glossary_aliases(key)
            if not keywords:
                continue
            if any(kw in raw_text for kw in keywords):
                dst = _glossary_destination(val)
                for alias in keywords:
                    previous_destinations = destinations_by_alias.get(alias, [])
                    if (
                        (is_additional or alias in aliases_with_additional_terms)
                        and any(previous != dst for previous in previous_destinations)
                    ):
                        raise ValueError(
                            "Glossary entries resolve to conflicting source terms."
                        )
                for alias in keywords:
                    destinations_by_alias.setdefault(alias, []).append(dst)
                    if is_additional:
                        aliases_with_additional_terms.add(alias)

                result = {
                    "src": keywords[0],
                    "dst": dst,
                    "info": str(val).strip(),
                }
                if is_additional and result in results:
                    continue
                results.append(result)
        return results

    def _parse_guidelines_content(self) -> Tuple[str, Dict[float, str]]:
        """Parse guidelines text into global rules and chapter-specific mappings."""
        if not self.guidelines_raw:
            return "", {}
        pattern = r"(《翻译指导原则》\s*-\s*\[(?:全局通用|第\s*\d+(?:\.\d+)?\s*章)\])"
        parts = re.split(pattern, self.guidelines_raw)
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
                match = re.search(r"第\s*(\d+(?:\.\d+)?)\s*章", header)
                if match:
                    chapter_dict[float(match.group(1))] = content
        return "\n\n".join(global_parts).strip(), chapter_dict

    def _load_current_chapter_raw(self, chapter_filename: str) -> str:
        """Attempt to read raw chapter text from expected locations."""
        base_dir = os.path.dirname(os.path.dirname(self.guidelines_path))
        raw_roots = [
            os.path.join(base_dir, "生肉"),
            os.path.join(base_dir, "生肉", "1.神んてらの世界"),
            os.path.join(os.getcwd(), "生肉"),
            os.path.join(os.getcwd(), "生肉", "1.神んてらの世界"),
        ]
        for root in raw_roots:
            try:
                return read_child_text(root, chapter_filename)
            except (OSError, ValueError):
                continue
        return ""

    def _find_tm_filename(self, chap_num: float) -> Optional[str]:
        """Find the filename matching chapter number in translation memory."""
        for fn in self.tm_retrieval_data.get("chapters", {}):
            if extract_chapter_num(fn, default=0.0) == chap_num:
                return fn
        return None

    def _get_chapter_tm_embedding(
        self, filename: str, expected_identity: dict
    ) -> Optional[np.ndarray]:
        """Compute the average paragraph embedding for chapter in TM."""
        if not hasattr(self, '_chapter_tm_embeddings_cache'):
            self._chapter_tm_embeddings_cache = {}
        identity_key = json.dumps(expected_identity, sort_keys=True)
        cache_key = (filename, identity_key)
        if cache_key in self._chapter_tm_embeddings_cache:
            return self._chapter_tm_embeddings_cache[cache_key]

        pairs = self.tm_retrieval_data.get("chapters", {}).get(filename, [])
        vectors = []
        for pair in pairs:
            if not isinstance(pair, dict):
                continue
            emb = pair.get("embedding")
            identity = pair.get("embedding_identity")
            if (
                identity == expected_identity
                and is_compatible_embedding(emb, identity)
            ):
                vectors.append(emb)
        result = np.mean(vectors, axis=0) if vectors else None
        self._chapter_tm_embeddings_cache[cache_key] = result
        return result

    def _find_best_semantic_match(self, curr_emb: np.ndarray, candidates: list) -> Optional[float]:
        """Compare current chapter embedding with candidates and select highest similarity."""
        best_sim = -1.0
        best_chap = None
        curr_identity = embedding_identity_for_vector(curr_emb.tolist())
        for num in candidates:
            fn = self._find_tm_filename(num)
            if not fn:
                continue
            cand_emb = self._get_chapter_tm_embedding(fn, curr_identity)
            if cand_emb is None:
                continue
            curr_norm = np.linalg.norm(curr_emb) or 1e-9
            cand_norm = np.linalg.norm(cand_emb) or 1e-9
            sim = np.dot(curr_emb, cand_emb) / (curr_norm * cand_norm)
            if sim > best_sim:
                best_sim = sim
                best_chap = num
        return best_chap

    def _semantic_fallback(
        self,
        target_chap: float,
        chapter_dict: dict,
        chapter_filename: str,
        current_raw_text: Optional[str] = None,
    ) -> str:
        """Perform semantic similarity fallback matching among adjacent chapters."""
        if not chapter_dict:
            return ""
        candidates = [num for num in [target_chap - 1, target_chap - 2, target_chap + 1, target_chap + 2] if num in chapter_dict]
        if not candidates:
            closest_num = min(chapter_dict.keys(), key=lambda k: abs(k - target_chap))
            return chapter_dict[closest_num]
        try:
            curr_text = (
                current_raw_text
                if current_raw_text is not None
                else self._load_current_chapter_raw(chapter_filename)
            )
            paras = [p.strip() for p in curr_text.split("\n\n") if p.strip()][:3]
            if paras:
                curr_embs = [self._generate_embedding_sync(p) for p in paras]
                curr_emb = np.mean(curr_embs, axis=0)
                best_chap = self._find_best_semantic_match(curr_emb, candidates)
                if best_chap is not None:
                    return chapter_dict[best_chap]
        except Exception as e:
            logger.warning(
                "Semantic fallback failed for chapter %s (%s).",
                chapter_filename,
                type(e).__name__,
            )
            pass
        closest_num = min(candidates, key=lambda k: abs(k - target_chap))
        return chapter_dict[closest_num]

    def get_partitioned_guidelines(
        self,
        chapter_filename: str,
        current_raw_text: Optional[str] = None,
        chapter_position: Optional[int] = None,
    ) -> str:
        """Retrieve global and matching/semantic-fallback chapter guidelines under 10KB."""
        global_guidelines, chapter_dict = self._parse_guidelines_content()
        target_chap = (
            chapter_position
            if chapter_position is not None
            else extract_chapter_num(chapter_filename, default=0.0)
        )

        if target_chap in chapter_dict:
            matched_content = chapter_dict[target_chap]
        else:
            matched_content = self._semantic_fallback(
                target_chap,
                chapter_dict,
                chapter_filename,
                current_raw_text=current_raw_text,
            )

        combined = f"{global_guidelines}\n\n{matched_content}".strip()

        # Constrain combined size to <10KB (using 9500 bytes to ensure safety margin)
        max_bytes = 9500
        combined_bytes = combined.encode("utf-8")
        if len(combined_bytes) > max_bytes:
            truncated = combined_bytes[:max_bytes].decode("utf-8", errors="ignore")
            combined = truncated + "\n... [Truncated due to length limit]"

        return combined

    @property
    def tm_disk_sha256(self):
        return self._tm_disk_sha256

    def _read_tm_disk_sha256(self):
        tm_file = Path(self.tm_path)
        if tm_file.is_symlink():
            raise ValueError("Symbolic links are not allowed for translation memory.")
        try:
            with open_regular_file(tm_file, binary=True) as stream:
                content = stream.read()
        except FileNotFoundError:
            return None
        return hashlib.sha256(content).hexdigest()

    def current_tm_disk_sha256(self):
        return self._read_tm_disk_sha256()

    def reload_translation_memory(self):
        """Reload the TM snapshot and its byte fingerprint from disk."""
        tm_file = Path(self.tm_path)
        if tm_file.is_symlink():
            raise ValueError("Symbolic links are not allowed for translation memory.")
        try:
            with open_regular_file(tm_file, binary=True) as stream:
                content = stream.read()
        except FileNotFoundError:
            self.tm_data = {"chapters": {}}
            self._tm_disk_sha256 = None
            return

        try:
            data = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.logger.error(
                "Failed to decode translation memory JSON file '%s' (%s).",
                self.tm_path,
                type(exc).__name__,
            )
            raise
        if not isinstance(data, dict) or not isinstance(data.get("chapters"), dict):
            raise ValueError("Translation memory must contain a chapters object.")
        self.tm_data = data
        self._tm_disk_sha256 = hashlib.sha256(content).hexdigest()
        if hasattr(self, "_chapter_tm_embeddings_cache"):
            self._chapter_tm_embeddings_cache.clear()

    def update_translation_memory(
        self,
        chapter_filename: str,
        paragraph_pairs: List[Dict[str, Any]],
        source_provenance: Optional[dict] = None,
        expected_tm_sha256=_EXPECTED_TM_HASH_UNSET,
    ):
        """Append paragraph pairs with embedding vectors and persist updated database."""
        if (
            expected_tm_sha256 is not _EXPECTED_TM_HASH_UNSET
            and expected_tm_sha256 != self._tm_disk_sha256
        ):
            raise ValueError(
                "Translation memory base changed since the update was prepared."
            )
        if self.current_tm_disk_sha256() != self._tm_disk_sha256:
            raise RuntimeError(
                "Translation memory changed on disk; reload before updating."
            )

        provenance_by_chapter = self.tm_data.get("source_provenance")
        if (
            "source_provenance" in self.tm_data
            and not isinstance(provenance_by_chapter, dict)
        ):
            raise ValueError("TM source_provenance must be an object.")

        if source_provenance is not None:
            pair_count = sum(
                1
                for pair in paragraph_pairs
                if pair.get("raw", "").strip()
                and pair.get("translated", "").strip()
            )
            validate_tm_source_provenance(source_provenance, pair_count)

        new_pairs = []
        for pair in paragraph_pairs:
            raw_text = pair.get("raw", "")
            translated_text = pair.get("translated", "")
            if not raw_text.strip() or not translated_text.strip():
                continue
            embedding = pair.get("embedding")
            embedding_identity = pair.get("embedding_identity")
            if not is_compatible_embedding(embedding, embedding_identity):
                try:
                    embedding = self._generate_embedding_sync(raw_text)
                except Exception as e:
                    logger.warning(
                        "Failed to generate embedding for raw text (%s).",
                        type(e).__name__,
                    )
                    raise RuntimeError(
                        "Translation-memory embedding failed; the TM update was aborted."
                    ) from None
                embedding_identity = embedding_identity_for_vector(embedding)
            new_pairs.append({
                "raw": raw_text,
                "translated": translated_text,
                "embedding": embedding,
                "embedding_identity": embedding_identity,
            })

        updated_tm_data = dict(self.tm_data)
        updated_tm_data["chapters"] = dict(self.tm_data.get("chapters", {}))
        updated_tm_data["chapters"][chapter_filename] = new_pairs

        if source_provenance is not None:
            provenance_by_chapter = dict(provenance_by_chapter or {})
            provenance_by_chapter[chapter_filename] = source_provenance
            updated_tm_data["source_provenance"] = provenance_by_chapter
        elif provenance_by_chapter is not None:
            provenance_by_chapter = dict(provenance_by_chapter)
            provenance_by_chapter.pop(chapter_filename, None)
            if provenance_by_chapter:
                updated_tm_data["source_provenance"] = provenance_by_chapter
            else:
                updated_tm_data.pop("source_provenance", None)

        try:
            content = json.dumps(
                updated_tm_data,
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            if self.current_tm_disk_sha256() != self._tm_disk_sha256:
                raise RuntimeError(
                    "Translation memory changed on disk; reload before updating."
                )
            write_bytes_atomically(self.tm_path, content)
        except Exception:
            logger.exception("Failed to write translation memory to %s", self.tm_path)
            raise

        self.tm_data = updated_tm_data
        self._tm_disk_sha256 = hashlib.sha256(content).hexdigest()
        if hasattr(self, "_chapter_tm_embeddings_cache"):
            for cache_key in list(self._chapter_tm_embeddings_cache):
                if (
                    isinstance(cache_key, tuple)
                    and cache_key[0] == chapter_filename
                ) or cache_key == chapter_filename:
                    self._chapter_tm_embeddings_cache.pop(cache_key, None)
