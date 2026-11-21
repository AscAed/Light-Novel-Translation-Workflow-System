import asyncio
import hashlib
import os
import json
import re
import urllib.request
import logging
import ipaddress
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlsplit
from chapter_transaction import (
    commit_chapter_translation,
    has_pending_chapter_transaction,
    is_chapter_translation_committed,
    recover_chapter_translation,
)
from scripts.ingest_kakuyomu_pages import _load_catalog_snapshot
from utils import (
    extract_chapter_num,
    open_regular_file,
    parse_api_timeout,
    parse_provider_data_policy,
    read_child_text,
    read_relative_text,
    reject_knowledge_draft_path,
    require_provider_data_authorized,
    require_aligned_annotations,
    require_aligned_paragraphs,
    resolve_child_path,
    resolve_relative_path,
    split_paragraphs,
    write_text_atomically,
)
from openai import (
    APIConnectionError,
    APIStatusError,
    AsyncOpenAI,
    DefaultAsyncHttpxClient,
)
from rag_engine import RAGEngine
from source_manifest import (
    load_manifest,
    verify_current_normalized_source,
    verify_current_normalized_source_metadata,
)
from source_editions import (
    read_verified_ai_edition_bytes,
    verify_ai_edition_index,
)
from story_summary_review import load_reviewed_story_summary


def _default_ai_edition_config(workspace_dir: str) -> dict:
    """Resolve the project's verified AI edition required by project mode."""
    workspace = Path(workspace_dir)
    source_root = workspace / "SourceArchive"
    ai_root = workspace / "RAWs_AI"
    if not source_root.exists() and not ai_root.exists():
        raise FileNotFoundError(
            "Project translation input requires a verified AI edition "
            "in SourceArchive and RAWs_AI; use an explicit JSON config "
            "to select another source."
        )
    if not source_root.is_dir() or not ai_root.is_dir():
        raise FileNotFoundError(
            "Project AI translation input requires both SourceArchive and RAWs_AI."
        )

    verified = verify_ai_edition_index(
        source_root=str(source_root),
        ai_root=str(ai_root),
        source_manifest_relative_path="source_manifest.json",
        edition_manifest_relative_path="source_editions_manifest.json",
    )
    index = verified["index"]
    work_id = index["work_id"]
    if not isinstance(work_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", work_id):
        raise ValueError("AI edition index contains an invalid work ID.")

    catalog_record = index.get("catalog")
    if (
        not isinstance(catalog_record, dict)
        or not isinstance(catalog_record.get("relative_path"), str)
        or not isinstance(catalog_record.get("sha256"), str)
    ):
        raise ValueError("AI edition index is missing its source catalog identity.")
    catalog = _load_catalog_snapshot(
        str(source_root),
        catalog_record["relative_path"],
    )
    if (
        catalog["work_id"] != work_id
        or catalog["sha256"] != catalog_record["sha256"]
    ):
        raise ValueError("AI edition index is stale for its source catalog.")
    catalog_episodes = {
        episode.metadata.episode_id: episode.metadata
        for episode in catalog["episodes"]
    }

    episodes = index["episodes"]
    if not episodes or set(catalog_episodes) != {
        episode.get("episode_id") for episode in episodes
    }:
        raise ValueError("AI edition index does not cover the complete catalog.")
    chapter_map = []
    seen_ids = set()
    seen_positions = set()
    for episode in episodes:
        episode_id = episode.get("episode_id")
        position = episode.get("position")
        metadata = catalog_episodes.get(episode_id)
        if (
            not isinstance(episode_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", episode_id)
            or episode_id in seen_ids
            or isinstance(position, bool)
            or not isinstance(position, int)
            or position < 1
            or position in seen_positions
            or metadata is None
            or metadata.position != position
            or metadata.title != episode.get("title")
        ):
            raise ValueError(
                "AI edition index episode metadata does not match its catalog."
            )
        raw_file = episode.get("ai_archive_relative_path")
        source_input_file = episode.get("ai_relative_path")
        source_sha256 = episode.get("output_sha256")
        source_version_id = episode.get("ai_edition_version_id")
        if (
            not isinstance(raw_file, str)
            or not isinstance(source_input_file, str)
            or not isinstance(source_sha256, str)
            or not isinstance(source_version_id, str)
        ):
            raise ValueError("AI edition index is missing an archived source version.")
        seen_ids.add(episode_id)
        seen_positions.add(position)
        chapter_map.append(
            {
                "raw_file": raw_file,
                "source_input_file": source_input_file,
                "source_sha256": source_sha256,
                "translation_file": (
                    f"episode-{position:04d}-{episode_id}.md"
                ),
                "tm_key": f"source-edition:{work_id}:{episode_id}",
                "source_version_id": source_version_id,
                "chapter_position": position,
            }
        )

    chapter_map.sort(key=lambda chapter: chapter["chapter_position"])
    return {
        "source_root": str(source_root),
        "ai_edition_root": str(ai_root),
        "source_manifest_path": "source_editions_manifest.json",
        "chapter_map": chapter_map,
    }


def _resolve_project_content_dir(
    workspace_dir: str, directory_name: str, config_name: str
) -> str:
    content_dir = os.path.join(workspace_dir, directory_name)
    if not os.path.isdir(content_dir):
        return content_dir

    nested_dirs = [
        entry
        for entry in os.listdir(content_dir)
        if os.path.isdir(os.path.join(content_dir, entry))
    ]
    if nested_dirs:
        raise ValueError(
            f"Project {config_name} contains subdirectories; set both RAW_DIR "
            "and OUTPUT_DIR in an explicit --config file."
        )
    return content_dir


def _load_project_workflow_path_settings(workspace_dir: str) -> Optional[dict]:
    settings_path = Path(workspace_dir) / "workflow_paths.json"
    if settings_path.is_symlink():
        raise ValueError("Project workflow path settings cannot be a symbolic link.")
    if not settings_path.exists():
        return None

    with open_regular_file(settings_path) as stream:
        settings = json.load(stream, object_pairs_hook=_reject_duplicate_json_fields)
    allowed_fields = {
        "schema_version",
        "output_dir",
        "human_edition_root",
    }
    if (
        not isinstance(settings, dict)
        or not {"schema_version", "output_dir"}.issubset(settings)
        or not set(settings).issubset(allowed_fields)
        or isinstance(settings.get("schema_version"), bool)
        or settings.get("schema_version") != 1
        or any(
            not isinstance(settings.get(key), str)
            or not settings[key].strip()
            for key in ("output_dir", "human_edition_root")
            if key in settings
        )
    ):
        raise ValueError(
            "Project workflow path settings require schema_version and "
            "output_dir, with optional human_edition_root."
        )
    return settings


def _resolve_configured_project_path(
    workspace_dir: str,
    value: str,
    *,
    must_exist: bool,
    setting_name: str,
) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = Path(workspace_dir) / path
    if path.is_symlink():
        raise ValueError(f"Configured project {setting_name} cannot be a symbolic link.")
    path = path.resolve(strict=must_exist)
    if path.exists() and not path.is_dir():
        raise NotADirectoryError(
            f"Configured project {setting_name} is not a directory."
        )
    if must_exist and not path.is_dir():
        raise NotADirectoryError(
            f"Configured project {setting_name} is not a directory."
        )
    return path


def _resolve_project_human_edition_root(workspace_dir: str) -> str:
    settings = _load_project_workflow_path_settings(workspace_dir)
    value = (
        settings.get("human_edition_root")
        if settings is not None
        else None
    )
    if value is None:
        return str(Path(workspace_dir) / "生肉")
    human_path = _resolve_configured_project_path(
        workspace_dir,
        value,
        must_exist=False,
        setting_name="human_edition_root",
    )
    return str(human_path)


def _resolve_project_output_override(workspace_dir: str) -> Optional[str]:
    settings = _load_project_workflow_path_settings(workspace_dir)
    if settings is None:
        return None

    output_path = _resolve_configured_project_path(
        workspace_dir,
        settings["output_dir"],
        must_exist=True,
        setting_name="output_dir",
    )
    protected_roots = (
        Path(workspace_dir) / "SourceArchive",
        Path(workspace_dir) / "RAWs_AI",
        Path(workspace_dir) / "生肉",
    )
    human_edition_root = settings.get("human_edition_root")
    if human_edition_root:
        protected_roots += (
            _resolve_configured_project_path(
                workspace_dir,
                human_edition_root,
                must_exist=False,
                setting_name="human_edition_root",
            ),
        )
    for protected_root in protected_roots:
        try:
            source_path = protected_root.resolve(strict=False)
            common = Path(os.path.commonpath((str(output_path), str(source_path))))
        except (OSError, ValueError):
            continue
        if common == output_path or common == source_path:
            raise ValueError(
                "Configured project output_dir must not overlap source directories."
            )
    return str(output_path)


def _reject_unreviewed_project_publication(
    workspace_dir: str,
    output_dir: str,
    chapter_map: Optional[list] = None,
) -> None:
    """Keep compatibility runs away from project publication targets."""
    if not isinstance(output_dir, str) or not output_dir:
        return

    output_path = Path(output_dir).resolve(strict=False)
    target_paths = [output_path]
    if isinstance(chapter_map, list):
        for item in chapter_map:
            if isinstance(item, dict) and isinstance(
                item.get("translation_file"), str
            ):
                target_paths.append(
                    (Path(output_dir) / item["translation_file"]).resolve(
                        strict=False
                    )
                )
    publication_roots = []
    if workspace_dir and Path(workspace_dir).is_dir():
        workspace_path = Path(workspace_dir).resolve(strict=True)
        publication_roots.append(workspace_path / "熟肉")
        configured_output = _resolve_project_output_override(
            str(workspace_path)
        )
        if configured_output:
            publication_roots.append(Path(configured_output))

    output_parts = output_path.parts
    for index, part in enumerate(output_parts):
        if part == "熟肉":
            publication_roots.append(Path(*output_parts[: index + 1]))

    target_keys = [os.path.normcase(str(path)) for path in target_paths]
    for root in publication_roots:
        root_path = root.resolve(strict=False)
        root_key = os.path.normcase(str(root_path))
        for target_key in target_keys:
            try:
                common = os.path.commonpath((target_key, root_key))
            except ValueError:
                continue
            if common == root_key:
                raise ValueError(
                    "Unreviewed translation cannot write to a project publication "
                    "directory; use scripts/run_kakuyomu_workflow.py to create "
                    "reviewable drafts."
                )


def _reject_duplicate_json_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Project workflow path settings contain duplicate fields.")
        result[key] = value
    return result


# Monkey-patch for aiohttp < 3.9.0 where ClientConnectorDNSError is missing
import aiohttp
if not hasattr(aiohttp, 'ClientConnectorDNSError'):
    class ClientConnectorDNSError(aiohttp.ClientConnectorError):
        pass
    aiohttp.ClientConnectorDNSError = ClientConnectorDNSError

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ResponseContractError(ValueError):
    """Raised when a model response cannot be parsed into its required contract."""


class TranslationQualityGateError(RuntimeError):
    """Raised when a formal project translation cannot pass a quality stage."""

    def __init__(self, message: str, *, chapter_position: Optional[int] = None):
        super().__init__(message)
        self.chapter_position = chapter_position


# Monkey-patch to prevent socket.getfqdn hang in proxy_bypass on Windows
orig_proxy_bypass = urllib.request.proxy_bypass
def patched_proxy_bypass(host):
    try:
        return orig_proxy_bypass(host)
    except Exception:
        return False
urllib.request.proxy_bypass = patched_proxy_bypass

class Config:
    WORKSPACE_DIR = os.environ.get("TEST_WORKSPACE_DIR", "")
    RAW_DIR = ""
    AI_EDITION_ROOT = None
    OUTPUT_DIR = ""
    TRANSLATION_OUTPUT_MODE = None
    CHAPTER_MAP = None
    SOURCE_MANIFEST_PATH = None
    TM_REVIEWED_PATH = None
    ALLOW_UNREVIEWED_TM = False
    REQUIRE_REVIEWED_PUBLICATION = False
    TRANSLATION_RUN_ID = None
    GLOSSARY_PATH = ""
    REQUIRE_REVIEWED_GLOSSARY = False
    GUIDELINES_PATH = ""
    INFO_PATH = ""
    
    STRICT_REFLECTION_MODE = False

    # Models
    INITIAL_MODEL = "sakura-14b"
    PROOFREAD_MODEL = "deepseek-v4-flash"
    STYLE_MODEL = "deepseek-v4-pro"
    FINAL_REVIEW_MODEL = None
    JYQF_FALLBACK_ENABLED = False
    
    # Sampling Parameters
    TRANSLATOR_PARAMS = {"temperature": 0.2, "top_p": 0.8}
    PROOFREADER_PARAMS = {"temperature": 0.1, "top_p": 0.7}
    POLISHER_PARAMS = {"temperature": 0.75, "top_p": 0.9}
    
    # Providers & Keys
    CODING_PLAN_BASE_URL = "https://coding.dashscope.aliyuncs.com/v1"
    CODING_PLAN_API_KEY = None
    GEMINI_API_KEY = None
    
    # Provider Base URLs. JOJO/JYQF are opt-in aliases for the user-selected
    # channels; the default model configuration remains unchanged until the
    # real endpoints and credentials are verified.
    SAKURA_BASE_URL = "http://127.0.0.1:6006/v1"
    DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
    JOJO_BASE_URL = "https://max2.jojocode.com/v1"
    JYQF_BASE_URL = "https://jyqf.me/v1"
    
    STORY_SUMMARY_PATH = ""
    REQUIRE_REVIEWED_STORY_SUMMARY = False
    EXPECTED_BOOK_BUNDLE = None
    REQUIRE_REVIEWED_CHAPTER_KNOWLEDGE = False
    TM_PATH = ""
    
    EXECUTION_MODE = "CODING_PLAN"
    CLI_COMMAND = "gemini"
    MIN_JITTER = 2
    MAX_JITTER = 5
    DEFAULT_API_TIMEOUT = 10.0
    API_TIMEOUT = DEFAULT_API_TIMEOUT
    GEMINI_FALLBACK_ENABLED = False
    PROVIDER_DATA_POLICY = {}
    SAFE_MODE = False
    WORK_DISCLAIMER = (
        "**[TRANSLATION_TASK]**\n"
        "请忠实处理用户提供的虚构作品文本，保留原意和语气，不补写或删减情节，并遵守所用服务适用的内容政策与安全要求。\n"
    )

    @classmethod
    def _apply_model_environment_overrides(cls):
        for name in (
            "INITIAL_MODEL",
            "PROOFREAD_MODEL",
            "STYLE_MODEL",
            "FINAL_REVIEW_MODEL",
        ):
            value = os.environ.get(name)
            if value is not None:
                setattr(cls, name, value)

    @classmethod
    def load_config(cls, project: Optional[str] = None, config_file: Optional[str] = None):
        cls.FINAL_REVIEW_MODEL = None
        cls.TRANSLATION_OUTPUT_MODE = None
        cls.CHAPTER_MAP = None
        cls.SOURCE_MANIFEST_PATH = None
        cls.AI_EDITION_ROOT = None
        cls.REQUIRE_REVIEWED_PUBLICATION = False
        cls.TRANSLATION_RUN_ID = None
        cls.REQUIRE_REVIEWED_STORY_SUMMARY = False
        cls.EXPECTED_BOOK_BUNDLE = None
        cls.REQUIRE_REVIEWED_CHAPTER_KNOWLEDGE = False
        cls.REQUIRE_REVIEWED_GLOSSARY = False
        cls.TM_REVIEWED_PATH = None
        cls.ALLOW_UNREVIEWED_TM = False
        if config_file and not Path(config_file).is_file():
            raise FileNotFoundError(f"Configuration file not found: {config_file}")

        # Tests use an isolated environment and must not inherit the repository's .env.
        if "TEST_WORKSPACE_DIR" not in os.environ:
            env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
            if os.path.exists(env_file):
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

        cls.GEMINI_FALLBACK_ENABLED = os.environ.get("ENABLE_GEMINI_FALLBACK", "").lower() in {
            "1", "true", "yes", "on"
        }
        cls.JYQF_FALLBACK_ENABLED = os.environ.get(
            "ENABLE_JYQF_FALLBACK", ""
        ).lower() in {"1", "true", "yes", "on"}
                        
        # Override Config paths if test workspace is provided
        if "TEST_WORKSPACE_DIR" in os.environ:
            cls.WORKSPACE_DIR = os.environ["TEST_WORKSPACE_DIR"]
            if not cls.WORKSPACE_DIR:
                cls.WORKSPACE_DIR = "/tmp/test_workspace"
                os.makedirs(cls.WORKSPACE_DIR, exist_ok=True)
            cls.RAW_DIR = os.path.join(cls.WORKSPACE_DIR, "生肉")
            cls.OUTPUT_DIR = os.path.join(cls.WORKSPACE_DIR, "translated")
            cls.TRANSLATION_OUTPUT_MODE = "test_draft"
            cls.GLOSSARY_PATH = os.path.join(cls.WORKSPACE_DIR, "Knowledge", "Glossary.json")
            cls.GUIDELINES_PATH = os.path.join(cls.WORKSPACE_DIR, "Knowledge", "guidelines.txt")
            cls.INFO_PATH = os.path.join(cls.WORKSPACE_DIR, "Knowledge", "作品基本信息.json")
            cls.STORY_SUMMARY_PATH = os.path.join(cls.WORKSPACE_DIR, "Knowledge", "STORY_SUMMARY.md")
            cls.TM_PATH = os.path.join(cls.WORKSPACE_DIR, "Knowledge", "translation_memory.json")

            test_path_mapping = {
                "TEST_RAW_DIR": "RAW_DIR",
                "TEST_OUTPUT_DIR": "OUTPUT_DIR",
                "TEST_GLOSSARY_PATH": "GLOSSARY_PATH",
                "TEST_GUIDELINES_PATH": "GUIDELINES_PATH",
                "TEST_INFO_PATH": "INFO_PATH",
                "TEST_STORY_SUMMARY_PATH": "STORY_SUMMARY_PATH",
                "TEST_TM_PATH": "TM_PATH",
                "TEST_TM_REVIEWED_PATH": "TM_REVIEWED_PATH",
            }
            for env_name, config_name in test_path_mapping.items():
                value = os.environ.get(env_name)
                if value:
                    setattr(cls, config_name, value)
            
            # Setup OpenAI-compatible provider URLs.
            for config_name in (
                "SAKURA_BASE_URL",
                "DEEPSEEK_BASE_URL",
                "JOJO_BASE_URL",
                "JYQF_BASE_URL",
            ):
                if config_name in os.environ:
                    setattr(cls, config_name, os.environ[config_name])
            cls.API_TIMEOUT = parse_api_timeout(
                os.environ.get("API_TIMEOUT", cls.DEFAULT_API_TIMEOUT)
            )
            cls.PROVIDER_DATA_POLICY = parse_provider_data_policy(
                os.environ.get("PROVIDER_DATA_POLICY", {})
            )
            cls.ALLOW_UNREVIEWED_TM = (
                os.environ.get("ALLOW_UNREVIEWED_TM", "").strip().lower()
                in {"1", "true", "yes", "on"}
            )
            cls._apply_model_environment_overrides()
            
            return

        # 2. Determine project name
        if not project and not config_file:
            try:
                import argparse
                parser = argparse.ArgumentParser(description="LN Translate Pipeline")
                parser.add_argument("--project", "-p", type=str)
                parser.add_argument("--config", "-c", type=str)
                args, _ = parser.parse_known_args()
                project = args.project
                config_file = args.config
            except Exception as e:
                logger.warning("Failed to parse command line arguments", exc_info=True)
                
        if not project and not config_file:
            project = os.environ.get("TRANSLATOR_PROJECT")
            
        if not project and not config_file:
            projects_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "projects")
            if os.path.exists(projects_dir):
                dirs = sorted(
                    d
                    for d in os.listdir(projects_dir)
                    if os.path.isdir(os.path.join(projects_dir, d))
                    and d != "example"
                )
                if len(dirs) == 1:
                    project = dirs[0]
                elif len(dirs) > 1:
                    raise ValueError(
                        "Multiple translation projects are available; "
                        "pass --project or set TRANSLATOR_PROJECT."
                    )
                    
        if project:
            # Prevent path traversal vulnerabilities
            if ".." in project or "/" in project or "\\" in project:
                raise ValueError("Invalid project name: path traversal detected")

        # 3. Resolve configuration
        cfg_data = {}
        if config_file:
            config_path = Path(config_file)
            if not config_path.is_file():
                raise FileNotFoundError(f"Configuration file not found: {config_path}")
            with config_path.open("r", encoding="utf-8") as f:
                cfg_data = json.load(f)
        elif project:
            base_projects_dir = os.path.realpath(
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "projects")
            )
            workspace_dir = os.path.realpath(os.path.join(base_projects_dir, project))
            try:
                workspace_is_child = (
                    os.path.commonpath((base_projects_dir, workspace_dir)) == base_projects_dir
                    and workspace_dir != base_projects_dir
                )
            except ValueError:
                workspace_is_child = False
            if not workspace_is_child:
                raise ValueError("Invalid project name: path traversal detected")
            if not os.path.isdir(workspace_dir):
                raise FileNotFoundError(f"Project directory not found: {workspace_dir}")
            cfg_data = {
                "WORKSPACE_DIR": workspace_dir,
                "TRANSLATION_OUTPUT_MODE": "reviewed_run_draft",
                "GLOSSARY_PATH": os.path.join(workspace_dir, "Knowledge", "Glossary.json"),
                "GUIDELINES_PATH": os.path.join(workspace_dir, "Knowledge", "guidelines.txt"),
                "INFO_PATH": os.path.join(workspace_dir, "Knowledge", "作品基本信息.json"),
                "STORY_SUMMARY_PATH": os.path.join(workspace_dir, "Knowledge", "STORY_SUMMARY.md"),
                "TM_PATH": os.path.join(workspace_dir, "Knowledge", "translation_memory.json"),
                "REQUIRE_REVIEWED_PUBLICATION": True,
            }
            if not os.path.exists(cfg_data["GLOSSARY_PATH"]):
                legacy_glossary = os.path.join(workspace_dir, "Glossary.json")
                if os.path.exists(legacy_glossary):
                    cfg_data["GLOSSARY_PATH"] = legacy_glossary
            if not os.path.exists(cfg_data["GUIDELINES_PATH"]):
                legacy_guidelines = os.path.join(workspace_dir, "guidelines.txt")
                if not os.path.exists(legacy_guidelines):
                    md_guidelines = os.path.join(workspace_dir, "Knowledge", "guidelines.md")
                    if os.path.exists(md_guidelines):
                        cfg_data["GUIDELINES_PATH"] = md_guidelines
                    else:
                        legacy_md_guidelines = os.path.join(workspace_dir, "guidelines.md")
                        if os.path.exists(legacy_md_guidelines):
                            cfg_data["GUIDELINES_PATH"] = legacy_md_guidelines
                else:
                    cfg_data["GUIDELINES_PATH"] = legacy_guidelines
            if not os.path.exists(cfg_data["INFO_PATH"]):
                legacy_info = os.path.join(workspace_dir, "作品基本信息.json")
                if os.path.exists(legacy_info):
                    cfg_data["INFO_PATH"] = legacy_info
            if not os.path.exists(cfg_data["STORY_SUMMARY_PATH"]):
                legacy_summary = os.path.join(workspace_dir, "STORY_SUMMARY.md")
                if os.path.exists(legacy_summary):
                    cfg_data["STORY_SUMMARY_PATH"] = legacy_summary
            cfg_data["STORY_SUMMARY_PATH"] = os.path.join(
                workspace_dir,
                "Knowledge",
                "STORY_SUMMARY_reviewed.json",
            )
            cfg_data["REQUIRE_REVIEWED_STORY_SUMMARY"] = True
            cfg_data["GLOSSARY_PATH"] = os.path.join(
                workspace_dir,
                "Knowledge",
                "Glossary_reviewed.json",
            )
            cfg_data["REQUIRE_REVIEWED_GLOSSARY"] = True
            cfg_data["REQUIRE_REVIEWED_CHAPTER_KNOWLEDGE"] = True

            ai_edition_config = _default_ai_edition_config(workspace_dir)
            cfg_data["RAW_DIR"] = ai_edition_config["source_root"]
            cfg_data["SOURCE_MANIFEST_PATH"] = ai_edition_config[
                "source_manifest_path"
            ]
            cfg_data["CHAPTER_MAP"] = ai_edition_config["chapter_map"]
            cfg_data["AI_EDITION_ROOT"] = ai_edition_config[
                "ai_edition_root"
            ]
            cfg_data["OUTPUT_DIR"] = _resolve_project_output_override(
                workspace_dir
            ) or _resolve_project_content_dir(workspace_dir, "熟肉", "OUTPUT_DIR")
        else:
            raise FileNotFoundError(
                "No translation project with a verified AI edition was selected; "
                "pass --project or configure an explicit JSON config."
            )

        if not isinstance(
            cfg_data.get("REQUIRE_REVIEWED_PUBLICATION", False),
            bool,
        ):
            raise ValueError(
                "REQUIRE_REVIEWED_PUBLICATION must be a boolean."
            )
        output_mode = cfg_data.get("TRANSLATION_OUTPUT_MODE")
        if output_mode is not None and not isinstance(output_mode, str):
            raise ValueError("TRANSLATION_OUTPUT_MODE must be a string.")
        if config_file and output_mode not in (None, "compatibility_draft"):
            raise ValueError(
                "Explicit JSON configuration may only declare "
                "TRANSLATION_OUTPUT_MODE='compatibility_draft'."
            )
        if (
            output_mode == "compatibility_draft"
            and cfg_data.get("REQUIRE_REVIEWED_PUBLICATION", False)
        ):
            raise ValueError(
                "compatibility_draft cannot enable reviewed project publication."
            )

        env_mapping = {
            "TEST_WORKSPACE_DIR": "WORKSPACE_DIR",
            "TEST_RAW_DIR": "RAW_DIR",
            "TEST_OUTPUT_DIR": "OUTPUT_DIR",
            "TEST_GLOSSARY_PATH": "GLOSSARY_PATH",
            "TEST_GUIDELINES_PATH": "GUIDELINES_PATH",
            "TEST_INFO_PATH": "INFO_PATH",
            "TEST_STORY_SUMMARY_PATH": "STORY_SUMMARY_PATH",
            "TEST_TM_PATH": "TM_PATH",
            "TEST_TM_REVIEWED_PATH": "TM_REVIEWED_PATH",
        }
        for env_k, cfg_k in env_mapping.items():
            val = os.environ.get(env_k)
            if val:
                cfg_data[cfg_k] = val

        for k, v in cfg_data.items():
            setattr(cls, k, v)
        cls._apply_model_environment_overrides()

        cls.TM_REVIEWED_PATH = os.environ.get(
            "TM_REVIEWED_PATH", cfg_data.get("TM_REVIEWED_PATH")
        )
        allow_unreviewed_tm = os.environ.get(
            "ALLOW_UNREVIEWED_TM",
            cfg_data.get("ALLOW_UNREVIEWED_TM", False),
        )
        cls.ALLOW_UNREVIEWED_TM = (
            str(allow_unreviewed_tm).strip().lower()
            in {"1", "true", "yes", "on"}
        )
        jyqf_fallback_enabled = os.environ.get(
            "ENABLE_JYQF_FALLBACK",
            cfg_data.get("ENABLE_JYQF_FALLBACK", False),
        )
        cls.JYQF_FALLBACK_ENABLED = (
            str(jyqf_fallback_enabled).lower() in {"1", "true", "yes", "on"}
        )

        cls.CODING_PLAN_API_KEY = os.environ.get("CODING_PLAN_API_KEY")
        cls.GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
        for config_name in (
            "SAKURA_BASE_URL",
            "DEEPSEEK_BASE_URL",
            "JOJO_BASE_URL",
            "JYQF_BASE_URL",
        ):
            setattr(
                cls,
                config_name,
                os.environ.get(config_name, getattr(cls, config_name)),
            )
        cls.API_TIMEOUT = parse_api_timeout(
            os.environ.get(
                "API_TIMEOUT",
                cfg_data.get("API_TIMEOUT", cls.DEFAULT_API_TIMEOUT),
            )
        )
        cls.PROVIDER_DATA_POLICY = parse_provider_data_policy(
            os.environ.get("PROVIDER_DATA_POLICY", cfg_data.get("PROVIDER_DATA_POLICY", {}))
        )

def load_json(path: str) -> Dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_text(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def save_text(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

def get_chapters(raw_dir: str) -> List[str]:
    files = []
    for filename in os.listdir(raw_dir):
        path = os.path.join(raw_dir, filename)
        if not filename.endswith(".md"):
            continue
        if os.path.islink(path):
            logger.warning("Skipping symlinked chapter entry: %s", filename)
            continue
        if os.path.isfile(path):
            files.append(filename)

    def sort_key(filename):
        match = re.search(r'第(\d+)話', filename)
        return int(match.group(1)) if match else float('inf')
    return sorted(files, key=sort_key)


@dataclass(frozen=True)
class ChapterSpec:
    raw_file: str
    translation_file: str
    tm_key: str
    source_version_id: Optional[str] = None
    chapter_position: Optional[int] = None
    source_input_file: Optional[str] = None
    source_sha256: Optional[str] = None


def get_chapter_specs(
    raw_dir: str,
    output_dir: str,
    chapter_map: Optional[list] = None,
    source_manifest_path: Optional[str] = None,
    source_input_root: Optional[str] = None,
) -> List[ChapterSpec]:
    """Resolve a reviewed chapter map, or preserve the legacy flat-directory scan."""
    if source_manifest_path is not None and (
        not isinstance(source_manifest_path, str)
        or not source_manifest_path
        or source_manifest_path.strip() != source_manifest_path
    ):
        raise ValueError("SOURCE_MANIFEST_PATH must be a trimmed relative path string.")
    if chapter_map is None:
        return [
            ChapterSpec(filename, filename, filename)
            for filename in get_chapters(raw_dir)
        ]
    if not isinstance(chapter_map, list) or not chapter_map:
        raise ValueError("CHAPTER_MAP must be a non-empty array.")

    specs = []
    raw_paths = set()
    translation_paths = set()
    tm_keys = set()
    expected_fields = {"raw_file", "translation_file", "tm_key"}
    source_manifest = None
    for index, item in enumerate(chapter_map, start=1):
        if (
            not isinstance(item, dict)
            or not expected_fields <= set(item)
            or not set(item)
            <= expected_fields
            | {
                "source_version_id",
                "chapter_position",
                "source_input_file",
                "source_sha256",
            }
        ):
            raise ValueError(
                f"CHAPTER_MAP entry {index} must contain exactly "
                "raw_file, translation_file, and tm_key, with optional "
                "source_version_id, chapter_position, source_input_file, "
                "and source_sha256."
            )
        raw_file = item["raw_file"]
        translation_file = item["translation_file"]
        tm_key = item["tm_key"]
        source_version_id = item.get("source_version_id")
        chapter_position = item.get("chapter_position")
        source_input_file = item.get("source_input_file")
        source_sha256 = item.get("source_sha256")
        if (
            not isinstance(raw_file, str)
            or not raw_file.lower().endswith(".md")
            or not isinstance(translation_file, str)
            or not translation_file.lower().endswith(".md")
        ):
            raise ValueError(
                f"CHAPTER_MAP entry {index} source and translation must be Markdown paths."
            )
        if (
            not isinstance(tm_key, str)
            or not tm_key.strip()
            or tm_key != tm_key.strip()
            or any(ord(character) < 32 for character in tm_key)
        ):
            raise ValueError(
                f"CHAPTER_MAP entry {index} requires a trimmed text tm_key "
                "without control characters."
            )

        raw_path = resolve_relative_path(
            raw_dir,
            raw_file,
            allow_missing=source_input_file is not None,
        )
        translation_path = resolve_relative_path(
            output_dir, translation_file, allow_missing=True
        )
        if source_input_file is None and not raw_path.is_file():
            raise ValueError(f"CHAPTER_MAP entry {index} source must be a regular file.")
        if "source_version_id" in item:
            if (
                not isinstance(source_version_id, str)
                or not source_version_id
                or source_version_id.strip() != source_version_id
                or any(ord(character) < 32 for character in source_version_id)
            ):
                raise ValueError(
                    f"CHAPTER_MAP entry {index} has an invalid source_version_id."
                )
            if not source_manifest_path:
                raise ValueError(
                    f"CHAPTER_MAP entry {index} requires SOURCE_MANIFEST_PATH "
                    "when source_version_id is set."
                )
            if source_manifest is None:
                source_manifest_file = resolve_relative_path(
                    raw_dir, source_manifest_path
                )
                source_manifest = load_manifest(source_manifest_file)
            source_artifact = (
                verify_current_normalized_source_metadata(
                    source_manifest, source_version_id
                )
                if source_input_file is not None
                else verify_current_normalized_source(
                    raw_dir, source_manifest, source_version_id
                )
            )
            if (
                source_artifact["kind"] != "normalized_source"
                or source_artifact["relative_path"] != raw_file
            ):
                raise ValueError(
                    f"CHAPTER_MAP entry {index} source version does not match "
                    "its normalized raw_file."
                )
        if source_input_file is not None:
            if (
                not isinstance(source_input_file, str)
                or not source_input_file.lower().endswith(".md")
                or not isinstance(source_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", source_sha256)
                or source_version_id is None
                or source_artifact["content_sha256"] != source_sha256
                or not isinstance(source_input_root, str)
                or not source_input_root
            ):
                raise ValueError(
                    f"CHAPTER_MAP entry {index} has an invalid AI edition input."
                )
            if source_artifact["content_sha256"] != source_sha256:
                raise ValueError(
                    f"CHAPTER_MAP entry {index} AI input hash does not match "
                    "its archived source version."
                )
            read_verified_ai_edition_bytes(
                source_input_root,
                source_input_file,
                source_sha256,
            )
        elif source_sha256 is not None and (
            not isinstance(source_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", source_sha256)
            or (
                source_version_id is not None
                and source_artifact["content_sha256"] != source_sha256
            )
        ):
            raise ValueError(
                f"CHAPTER_MAP entry {index} has an invalid source_sha256."
            )
        if "chapter_position" in item and (
            isinstance(chapter_position, bool)
            or not isinstance(chapter_position, int)
            or chapter_position < 1
        ):
            raise ValueError(
                f"CHAPTER_MAP entry {index} has an invalid chapter_position."
            )
        if translation_path.exists() and not translation_path.is_file():
            raise ValueError(
                f"CHAPTER_MAP entry {index} translation target must be a regular file."
            )

        raw_identity = os.path.normcase(str(raw_path))
        translation_identity = os.path.normcase(str(translation_path))
        tm_identity = tm_key.casefold()
        if raw_identity in raw_paths:
            raise ValueError(f"CHAPTER_MAP entry {index} repeats a raw_file.")
        if translation_identity in translation_paths:
            raise ValueError(f"CHAPTER_MAP entry {index} repeats a translation_file.")
        if tm_identity in tm_keys:
            raise ValueError(f"CHAPTER_MAP entry {index} repeats a tm_key.")
        raw_paths.add(raw_identity)
        translation_paths.add(translation_identity)
        tm_keys.add(tm_identity)
        specs.append(
            ChapterSpec(
                raw_file,
                translation_file,
                tm_key,
                source_version_id,
                chapter_position,
                source_input_file,
                source_sha256,
            )
        )
    return specs


def _read_chapter_source_text(spec, mapped_paths):
    if spec.source_input_file is not None:
        if not Config.AI_EDITION_ROOT or not spec.source_sha256:
            raise ValueError("AI edition input root and digest are required.")
        return read_verified_ai_edition_bytes(
            Config.AI_EDITION_ROOT,
            spec.source_input_file,
            spec.source_sha256,
        ).decode("utf-8")
    if mapped_paths:
        return read_relative_text(Config.RAW_DIR, spec.raw_file)
    return read_child_text(Config.RAW_DIR, spec.raw_file)


def get_sliced_story_summary(full_summary: str, current_chap_num: float, window_size: int = 5) -> str:
    lines = full_summary.split('\n')
    header_lines = []
    
    # Collect header lines
    for line in lines:
        line_stripped = line.strip()
        if line_stripped and re.match(r'^\[第\s*\d+(?:\.\d+)?\s*[話话]', line_stripped):
            break
        header_lines.append(line)
    header = "\n".join(header_lines).strip()
    
    # Parse all chapter summaries
    parsed_chapters = []
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue
        match = re.match(r'^\[第\s*(\d+(?:\.\d+)?)\s*[話话]', line_stripped)
        if match:
            try:
                num = float(match.group(1))
                parsed_chapters.append((num, line_stripped))
            except ValueError:
                pass
                
    parsed_chapters.sort(key=lambda x: x[0])
    selected_chapters = []
    
    # Always include Chapter 1
    chap_1 = next((item for item in parsed_chapters if item[0] == 1.0), None)
    if chap_1:
        selected_chapters.append(chap_1)
        
    prior_chapters = [item for item in parsed_chapters if item[0] < current_chap_num and item[0] != 1.0]
    recent_chapters = prior_chapters[-window_size:] if prior_chapters else []
    selected_chapters.extend(recent_chapters)
    
    unique_dict = {}
    for num, line_content in selected_chapters:
        unique_dict[num] = line_content
        
    sorted_selected = sorted(unique_dict.items(), key=lambda x: x[0])
    
    result = header + "\n\n"
    if sorted_selected:
        result += "\n\n".join([item[1] for item in sorted_selected])
    else:
        result += "尚无符合条件的故事概要。"
    return result

def extract_json(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    try:
        match = re.search(r'```(?:json)?\s*(\{.*\})\s*```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass
        start, end = text.find('{'), text.rfind('}')
        if start != -1 and end != -1:
            return json.loads(text[start:end+1])
        return json.loads(text.strip())
    except Exception:
        return {}

def get_base_url(default_url: str) -> str:
    mock_port = os.environ.get("MOCK_SERVER_PORT")
    if mock_port:
        return f"http://127.0.0.1:{mock_port}/v1"
    return default_url

def get_api_key(env_name: str) -> Optional[str]:
    return os.environ.get(env_name) or None


@dataclass(frozen=True)
class PrimaryProviderRoute:
    provider_id: str
    base_url: str
    api_key_env: str
    request_model: Optional[str] = None


SOURCE_AND_KNOWLEDGE_CATEGORIES = (
    "source_text",
    "book_knowledge",
)
FULL_TRANSLATION_CATEGORIES = (
    "source_text",
    "translation_text",
    "book_knowledge",
)


def get_primary_provider_route(model_name: str) -> PrimaryProviderRoute:
    if not isinstance(model_name, str) or not model_name.strip():
        raise ValueError("A non-empty model name is required for provider routing.")
    if model_name != model_name.strip():
        raise ValueError("Model names must not contain leading or trailing whitespace.")

    if model_name.startswith("pool:"):
        from api_pool import resolve_pool_route

        entry = resolve_pool_route(model_name)
        return PrimaryProviderRoute(
            entry["provider_id"], entry["base_url"], entry["key_env"], entry["model"]
        )

    lowered_name = model_name.lower()
    if (
        lowered_name == "sakura"
        or lowered_name.startswith("sakura-")
        or lowered_name.startswith("qwen3.6-plus")
    ):
        return PrimaryProviderRoute(
            "sakura",
            Config.SAKURA_BASE_URL,
            "SAKURA_API_KEY",
        )
    if lowered_name == "gpt-6-luna" or lowered_name.startswith("gpt-6-luna-"):
        return PrimaryProviderRoute(
            "jojo",
            Config.JOJO_BASE_URL,
            "JOJO_API_KEY",
        )
    if lowered_name == "deepseek-v4.1-flash":
        return PrimaryProviderRoute(
            "jyqf",
            Config.JYQF_BASE_URL,
            "JYQF_API_KEY",
        )
    if lowered_name.startswith("deepseek-"):
        return PrimaryProviderRoute(
            "deepseek",
            Config.DEEPSEEK_BASE_URL,
            "DEEPSEEK_API_KEY",
        )
    raise ValueError(
        "Unsupported model name for primary provider routing; "
        "supported names must start with sakura-, qwen3.6-plus, deepseek-, "
        "or use the configured gpt-6-luna/deepseek-v4.1-flash aliases."
    )


def _is_retryable_provider_error(error: Exception) -> bool:
    if isinstance(error, APIConnectionError):
        return True
    if isinstance(error, APIStatusError):
        return (
            error.status_code in (408, 429)
            or 500 <= error.status_code < 600
        )
    return False


def _is_loopback_url(base_url: str) -> bool:
    hostname = urlsplit(base_url).hostname
    if not hostname:
        return False
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def validate_provider_configuration() -> None:
    """Validate every configured pipeline stage before reading source chapters."""
    required_keys = set()
    has_jojo_stage = False
    stage_requests = [
        (Config.INITIAL_MODEL, SOURCE_AND_KNOWLEDGE_CATEGORIES),
        (Config.PROOFREAD_MODEL, SOURCE_AND_KNOWLEDGE_CATEGORIES),
        (Config.PROOFREAD_MODEL, FULL_TRANSLATION_CATEGORIES),
        (Config.STYLE_MODEL, FULL_TRANSLATION_CATEGORIES),
    ]
    if Config.STRICT_REFLECTION_MODE:
        stage_requests.append(
            (Config.INITIAL_MODEL, FULL_TRANSLATION_CATEGORIES)
        )
    for model, data_categories in stage_requests:
        route = get_primary_provider_route(model)
        base_url = validate_provider_base_url(get_base_url(route.base_url))
        endpoint_is_local = _is_loopback_url(base_url)
        require_provider_data_authorized(
            route.provider_id,
            data_categories,
            Config.PROVIDER_DATA_POLICY,
            endpoint_is_local=endpoint_is_local,
        )
        if not endpoint_is_local:
            required_keys.add(route.api_key_env)
        from api_pool import FALLBACK_ENV
        pool_fallback = os.environ.get(FALLBACK_ENV, "") if model.startswith("pool:") else ""
        if pool_fallback:
            if not pool_fallback.startswith("pool:") or pool_fallback == model:
                raise ValueError("API pool fallback must be a different configured pool slot.")
            fallback_route = get_primary_provider_route(pool_fallback)
            fallback_url = validate_provider_base_url(get_base_url(fallback_route.base_url))
            fallback_is_local = _is_loopback_url(fallback_url)
            require_provider_data_authorized(
                fallback_route.provider_id, data_categories,
                Config.PROVIDER_DATA_POLICY, endpoint_is_local=fallback_is_local,
            )
            if not fallback_is_local:
                required_keys.add(fallback_route.api_key_env)
        if route.provider_id == "jojo":
            has_jojo_stage = True
            if Config.JYQF_FALLBACK_ENABLED:
                fallback_route = get_primary_provider_route(
                    "deepseek-v4.1-flash"
                )
                fallback_url = validate_provider_base_url(
                    get_base_url(fallback_route.base_url)
                )
                fallback_is_local = _is_loopback_url(fallback_url)
                require_provider_data_authorized(
                    fallback_route.provider_id,
                    data_categories,
                    Config.PROVIDER_DATA_POLICY,
                    endpoint_is_local=fallback_is_local,
                )
                if not fallback_is_local:
                    required_keys.add(fallback_route.api_key_env)
        jyqf_handles_jojo_failures = (
            Config.JYQF_FALLBACK_ENABLED
            and route.provider_id == "jojo"
        )
        if (
            Config.GEMINI_FALLBACK_ENABLED
            and not jyqf_handles_jojo_failures
            and not pool_fallback
        ):
            require_provider_data_authorized(
                "gemini",
                data_categories,
                Config.PROVIDER_DATA_POLICY,
            )
            required_keys.add("GEMINI_API_KEY")
    if Config.JYQF_FALLBACK_ENABLED and not has_jojo_stage:
        raise ValueError(
            "JYQF fallback is enabled, but no pipeline stage uses the JOJO provider."
        )
    if "source_text" in Config.PROVIDER_DATA_POLICY.get(
        "gemini", frozenset()
    ):
        required_keys.add("GEMINI_API_KEY")
    missing = sorted(name for name in required_keys if not get_api_key(name))
    if os.environ.get("MOCK_SERVER_PORT"):
        missing = [name for name in missing if name != "GEMINI_API_KEY"]
    if missing:
        raise RuntimeError(
            f"Missing required provider credentials: {', '.join(missing)}"
        )


def _resolve_provider_route_identity(model_name: str):
    route = get_primary_provider_route(model_name)
    base_url = validate_provider_base_url(get_base_url(route.base_url))
    parsed = urlsplit(base_url)
    port = parsed.port
    if (parsed.scheme.lower(), port) in {("http", 80), ("https", 443)}:
        port = None
    identity = (
        parsed.scheme.lower(),
        (parsed.hostname or "").lower(),
        port,
        parsed.path.rstrip("/"),
        route.request_model or model_name,
    )
    return route, base_url, identity


def _provider_routes_are_independent(
    first_identity: tuple,
    second_identity: tuple,
) -> bool:
    return (
        first_identity[:-1] != second_identity[:-1]
        and first_identity[-1] != second_identity[-1]
    )


def validate_final_review_provider_configuration() -> None:
    """Validate the optional final-review route without starting a review call."""
    model = Config.FINAL_REVIEW_MODEL
    if not isinstance(model, str) or not model.strip():
        raise RuntimeError("FINAL_REVIEW_MODEL is not configured.")

    reviewer, reviewer_url, reviewer_identity = _resolve_provider_route_identity(
        model
    )
    _, _, translator_identity = _resolve_provider_route_identity(
        Config.INITIAL_MODEL
    )
    if not _provider_routes_are_independent(
        reviewer_identity,
        translator_identity,
    ):
        raise ValueError(
            "Final review must use a different endpoint and model from translation."
        )

    reviewer_is_local = _is_loopback_url(reviewer_url)
    require_provider_data_authorized(
        reviewer.provider_id,
        FULL_TRANSLATION_CATEGORIES,
        Config.PROVIDER_DATA_POLICY,
        endpoint_is_local=reviewer_is_local,
    )
    required_keys = set()
    if not reviewer_is_local:
        required_keys.add(reviewer.api_key_env)

    from api_pool import FALLBACK_ENV

    pool_fallback = (
        os.environ.get(FALLBACK_ENV, "") if model.startswith("pool:") else ""
    )
    if pool_fallback:
        if not pool_fallback.startswith("pool:") or pool_fallback == model:
            raise ValueError("API pool fallback must be a different configured pool slot.")
        fallback = get_primary_provider_route(pool_fallback)
        fallback_url = validate_provider_base_url(get_base_url(fallback.base_url))
        fallback_is_local = _is_loopback_url(fallback_url)
        require_provider_data_authorized(
            fallback.provider_id,
            FULL_TRANSLATION_CATEGORIES,
            Config.PROVIDER_DATA_POLICY,
            endpoint_is_local=fallback_is_local,
        )
        if not fallback_is_local:
            required_keys.add(fallback.api_key_env)
    elif reviewer.provider_id == "jojo" and Config.JYQF_FALLBACK_ENABLED:
        fallback = get_primary_provider_route("deepseek-v4.1-flash")
        fallback_url = validate_provider_base_url(get_base_url(fallback.base_url))
        fallback_is_local = _is_loopback_url(fallback_url)
        require_provider_data_authorized(
            fallback.provider_id,
            FULL_TRANSLATION_CATEGORIES,
            Config.PROVIDER_DATA_POLICY,
            endpoint_is_local=fallback_is_local,
        )
        if not fallback_is_local:
            required_keys.add(fallback.api_key_env)
    elif Config.GEMINI_FALLBACK_ENABLED:
        require_provider_data_authorized(
            "gemini",
            FULL_TRANSLATION_CATEGORIES,
            Config.PROVIDER_DATA_POLICY,
        )
        required_keys.add("GEMINI_API_KEY")

    missing = sorted(name for name in required_keys if not get_api_key(name))
    if os.environ.get("MOCK_SERVER_PORT"):
        missing = [name for name in missing if name != "GEMINI_API_KEY"]
    if missing:
        raise RuntimeError(
            f"Missing required provider credentials: {', '.join(missing)}"
        )


def validate_translation_rework_provider_configuration() -> None:
    """Validate the proofreading route used to generate bounded rework."""
    if not isinstance(Config.FINAL_REVIEW_MODEL, str) or not Config.FINAL_REVIEW_MODEL.strip():
        raise RuntimeError("FINAL_REVIEW_MODEL is not configured.")
    validate_provider_configuration()
    _, _, rework_identity = _resolve_provider_route_identity(
        Config.PROOFREAD_MODEL
    )
    _, _, reviewer_identity = _resolve_provider_route_identity(
        Config.FINAL_REVIEW_MODEL
    )
    if not _provider_routes_are_independent(
        rework_identity,
        reviewer_identity,
    ):
        raise ValueError(
            "Translation rework must use a different endpoint and model "
            "from the final reviewer."
        )


def validate_provider_base_url(base_url: str) -> str:
    if not isinstance(base_url, str) or not base_url or any(
        character.isspace() for character in base_url
    ):
        raise ValueError("Provider base URL must be a non-empty URL without whitespace.")
    try:
        parsed_url = urlsplit(base_url)
        hostname = parsed_url.hostname
        parsed_url.port
    except ValueError as exc:
        raise ValueError("Provider base URL is invalid.") from exc

    if parsed_url.scheme not in {"http", "https"} or not hostname:
        raise ValueError("Provider base URL must include an HTTP(S) scheme and host.")
    if parsed_url.username is not None or parsed_url.password is not None:
        raise ValueError("Provider credentials must use the API key setting, not the URL.")
    if parsed_url.query or parsed_url.fragment:
        raise ValueError("Provider base URL must not contain a query or fragment.")
    if parsed_url.scheme == "http" and not _is_loopback_url(base_url):
        raise ValueError("Non-loopback provider URLs must use HTTPS.")
    return base_url


def resolve_openai_client_settings(
    base_url: str,
    api_key: Optional[str],
    *,
    provider_id: Optional[str] = None,
    data_categories=None,
) -> Tuple[str, str]:
    resolved_base_url = validate_provider_base_url(get_base_url(base_url))
    require_provider_data_authorized(
        provider_id,
        data_categories,
        Config.PROVIDER_DATA_POLICY,
        endpoint_is_local=_is_loopback_url(resolved_base_url),
    )
    if not api_key:
        if not _is_loopback_url(resolved_base_url):
            raise RuntimeError("A provider-specific API key is required for this endpoint.")
        api_key = "local-no-auth"
    return resolved_base_url, api_key


def get_openai_client(
    base_url: str,
    api_key: Optional[str],
    *,
    provider_id: Optional[str] = None,
    data_categories=None,
    max_retries: Optional[int] = None,
) -> AsyncOpenAI:
    resolved_base_url, resolved_api_key = resolve_openai_client_settings(
        base_url,
        api_key,
        provider_id=provider_id,
        data_categories=data_categories,
    )
    http_client = DefaultAsyncHttpxClient(
        timeout=Config.API_TIMEOUT,
        follow_redirects=False,
    )
    client_options = {}
    if max_retries is not None:
        client_options["max_retries"] = max_retries
    return AsyncOpenAI(
        api_key=resolved_api_key,
        base_url=resolved_base_url,
        timeout=Config.API_TIMEOUT,
        http_client=http_client,
        **client_options,
    )

class UnifiedAgent:
    def __init__(self, model_name: str, system_instruction: str,
                 response_schema: Optional[Dict[str, Any]] = None,
                 static_context: str = "",
                 temperature: float = 0.1,
                 top_p: float = 1.0,
                 session_id: Optional[str] = None,
                 cached_content: Optional[str] = None,
                 agent_dir: Optional[str] = None,
                 include_dirs: Optional[List[str]] = None,
                 data_categories: Optional[List[str]] = None):
        self.model_name = model_name
        self.system_instruction = system_instruction
        self.response_schema = response_schema
        self.static_context = static_context
        self.temperature = temperature
        self.top_p = top_p
        self.data_categories = data_categories

    async def _call_primary(
        self,
        prompt: str,
        system_instr: str,
        *,
        route: Optional[PrimaryProviderRoute] = None,
        model_name: Optional[str] = None,
        max_retries: Optional[int] = None,
    ) -> Any:
        route = route or get_primary_provider_route(self.model_name)
        request_model = route.request_model or model_name or self.model_name
        api_key = get_api_key(route.api_key_env)
        
        client_options = {}
        if max_retries is not None:
            client_options["max_retries"] = max_retries
        client = get_openai_client(
            route.base_url,
            api_key,
            provider_id=route.provider_id,
            data_categories=self.data_categories,
            **client_options,
        )
        messages = [
            {"role": "system", "content": system_instr},
            {"role": "user", "content": prompt}
        ]
        
        response_format = {"type": "json_object"} if self.response_schema else None
        
        response = await client.chat.completions.create(
            model=request_model,
            messages=messages,
            temperature=self.temperature,
            top_p=self.top_p,
            response_format=response_format,
            max_tokens=4096
        )
        
        choice = response.choices[0]
        if choice.finish_reason == "content_filter":
            raise ContentBlockedError(
                "Content blocked by provider safety filter "
                "(finish_reason=content_filter)"
            )
            
        text = choice.message.content or ""
        if "Content blocked" in text:
            raise ContentBlockedError(
                "Content blocked by provider safety filter (Content blocked in text)"
            )
            
        if self.response_schema:
            res_dict = extract_json(text)
            if not res_dict:
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, TypeError) as exc:
                    raise ResponseContractError(
                        "Failed to extract JSON from provider response"
                    ) from exc
            return res_dict
            
        return text

    async def _call_jyqf(self, prompt: str, system_instr: str) -> Any:
        route = get_primary_provider_route("deepseek-v4.1-flash")
        base_url = validate_provider_base_url(get_base_url(route.base_url))
        require_provider_data_authorized(
            route.provider_id,
            self.data_categories,
            Config.PROVIDER_DATA_POLICY,
            endpoint_is_local=_is_loopback_url(base_url),
        )
        return await self._call_primary(
            prompt,
            system_instr,
            route=route,
            model_name="deepseek-v4.1-flash",
            max_retries=0,
        )

    async def _call_gemini(self, prompt: str, system_instr: str) -> Any:
        require_provider_data_authorized(
            "gemini",
            self.data_categories,
            Config.PROVIDER_DATA_POLICY,
        )
        from google import genai
        from google.genai import types
        
        gemini_key = get_api_key("GEMINI_API_KEY")
        client = genai.Client(
            api_key=gemini_key,
            http_options=types.HttpOptions(
                timeout=int(Config.API_TIMEOUT * 1000)
            ),
        )
        
        config_args = {
            "system_instruction": system_instr,
            "temperature": 0.1,
        }
        if self.response_schema:
            config_args["response_mime_type"] = "application/json"
            config_args["response_schema"] = self.response_schema
            
        config = types.GenerateContentConfig(**config_args)
        
        resp = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
            config=config
        )
        
        if not resp or not resp.text:
            if resp and resp.candidates and resp.candidates[0].finish_reason in ["SAFETY", "content_filter"]:
                raise Exception("Gemini Safety Blocked")
            raise Exception("Gemini returned empty response")
            
        if self.response_schema:
            res_dict = extract_json(resp.text)
            if not res_dict:
                raise ResponseContractError(
                    "Failed to extract JSON from Gemini response"
                )
            return res_dict
            
        return resp.text

    async def call(self, user_prompt: str, enable_thinking: bool = False) -> Any:
        full_sys = Config.WORK_DISCLAIMER + "\n"
        if self.static_context:
            full_sys += self.static_context + "\n\n"
        full_sys += self.system_instruction
        
        try:
            return await self._call_primary(user_prompt, full_sys)
        except Exception as primary_error:
            if isinstance(primary_error, ContentBlockedError) or not _is_retryable_provider_error(
                primary_error
            ):
                raise
            primary_route = get_primary_provider_route(self.model_name)
            from api_pool import FALLBACK_ENV
            pool_fallback = (
                os.environ.get(FALLBACK_ENV, "")
                if self.model_name.startswith("pool:") else ""
            )
            if pool_fallback:
                if not pool_fallback.startswith("pool:") or pool_fallback == self.model_name:
                    raise ValueError("API pool fallback must be a different configured pool slot.")
                fallback_route = get_primary_provider_route(pool_fallback)
                logger.warning("Primary API pool request failed; attempting the authorized fallback once.")
                return await self._call_primary(
                    user_prompt, full_sys, route=fallback_route, max_retries=0
                )
            if (
                Config.JYQF_FALLBACK_ENABLED
                and primary_route.provider_id == "jojo"
            ):
                logger.warning(
                    "JOJO invocation failed with retryable provider error (%s); "
                    "explicit JYQF fallback is enabled.",
                    type(primary_error).__name__,
                )
                return await self._call_jyqf(user_prompt, full_sys)
            if not Config.GEMINI_FALLBACK_ENABLED:
                raise
            if not get_api_key("GEMINI_API_KEY"):
                raise RuntimeError(
                    "Gemini fallback is enabled, but GEMINI_API_KEY is not configured."
                )
            logger.warning(
                "Primary model invocation failed with retryable provider error (%s); "
                "explicit Gemini fallback is enabled.",
                type(primary_error).__name__,
            )
            return await self._call_gemini(user_prompt, full_sys)


class ContentBlockedError(RuntimeError):
    pass


# Alias for backwards compatibility with tests
GeminiAgent = UnifiedAgent

class TranslationPipeline:
    def __init__(
        self,
        *,
        reviewed_tm_translation_root: Optional[str] = None,
    ):
        if not Config.WORKSPACE_DIR:
            Config.load_config()
        if Config.REQUIRE_REVIEWED_PUBLICATION:
            if Config.ALLOW_UNREVIEWED_TM:
                raise ValueError(
                    "Reviewed project translation cannot enable "
                    "unreviewed TM retrieval."
                )
            if Config.TRANSLATION_OUTPUT_MODE != "reviewed_run_draft":
                raise ValueError(
                    "Reviewed project drafts must be created through "
                    "scripts/run_kakuyomu_workflow.py."
                )
            run_id = Config.TRANSLATION_RUN_ID
            if not isinstance(run_id, str) or not re.fullmatch(
                r"[0-9a-f]{32}", run_id
            ):
                raise ValueError(
                    "Project translations must run through "
                    "scripts/run_kakuyomu_workflow.py to create reviewable drafts."
                )
            workspace_path = Path(Config.WORKSPACE_DIR).resolve(strict=True)
            expected_output = (
                workspace_path
                / "Workflow"
                / "Runs"
                / run_id
                / "Drafts"
            ).resolve(strict=True)
            configured_output = Path(Config.OUTPUT_DIR).resolve(strict=True)
            state_path = expected_output.parent / "run_state.json"
            with open_regular_file(state_path, binary=True) as stream:
                run_state = json.loads(stream.read(64 * 1024 + 1).decode("utf-8"))
            if (
                configured_output != expected_output
                or not isinstance(run_state, dict)
                or run_state.get("schema_version") != 1
                or run_state.get("status") != "running"
                or run_state.get("run_id") != run_id
            ):
                raise ValueError(
                    "Project translation output must remain inside its active review run."
                )
        else:
            if Config.TRANSLATION_OUTPUT_MODE not in {
                "compatibility_draft",
                "test_draft",
            }:
                raise ValueError(
                    "Unreviewed translations require an explicit "
                    "TRANSLATION_OUTPUT_MODE='compatibility_draft'."
                )
            _reject_unreviewed_project_publication(
                Config.WORKSPACE_DIR,
                Config.OUTPUT_DIR,
                Config.CHAPTER_MAP,
            )
        reject_knowledge_draft_path(Config.GLOSSARY_PATH, "glossary input")
        reject_knowledge_draft_path(
            Config.STORY_SUMMARY_PATH, "story summary input"
        )
        self.story_summary = ""
        self._stage_trace = {}
        source_input_map = {
            item["raw_file"]: {
                "source_version_id": item.get("source_version_id"),
                "source_input_file": item.get("source_input_file"),
                "source_sha256": item.get("source_sha256"),
            }
            for item in (Config.CHAPTER_MAP or [])
            if isinstance(item, dict)
            and isinstance(item.get("raw_file"), str)
            and item.get("source_input_file") is not None
        }
        source_input_root = (
            Config.AI_EDITION_ROOT if source_input_map else None
        )
        if Config.REQUIRE_REVIEWED_STORY_SUMMARY:
            if not os.path.exists(Config.STORY_SUMMARY_PATH):
                raise ValueError(
                    "Project translation requires an approved full-book "
                    "story summary for the current AI source edition."
                )
            chapter_specs = get_chapter_specs(
                Config.RAW_DIR,
                Config.OUTPUT_DIR,
                Config.CHAPTER_MAP,
                Config.SOURCE_MANIFEST_PATH,
                source_input_root=Config.AI_EDITION_ROOT,
            )
            expected_sources = [
                {
                    "filename": chapter.raw_file,
                    "source_version_id": chapter.source_version_id,
                    "source_input_file": chapter.source_input_file,
                    "source_sha256": chapter.source_sha256,
                }
                for chapter in chapter_specs
            ]
            if not expected_sources or any(
                not source["source_version_id"] for source in expected_sources
            ):
                raise ValueError(
                    "Project translation requires a complete versioned AI chapter map."
                )
            if not isinstance(Config.EXPECTED_BOOK_BUNDLE, dict):
                raise ValueError(
                    "Project translation requires the current verified AI book bundle."
                )
            self.story_summary = load_reviewed_story_summary(
                Config.STORY_SUMMARY_PATH,
                Config.RAW_DIR,
                Config.SOURCE_MANIFEST_PATH,
                require_full_book_coverage=True,
                require_book_bundle=True,
                expected_book_bundle=Config.EXPECTED_BOOK_BUNDLE,
                expected_sources=expected_sources,
                source_input_root=source_input_root,
                source_input_map=source_input_map,
            )
        elif os.path.exists(Config.STORY_SUMMARY_PATH):
            if Path(Config.STORY_SUMMARY_PATH).suffix.lower() == ".json":
                source_summary_kwargs = {}
                if source_input_map:
                    source_summary_kwargs = {
                        "source_input_root": source_input_root,
                        "source_input_map": source_input_map,
                    }
                self.story_summary = load_reviewed_story_summary(
                    Config.STORY_SUMMARY_PATH,
                    Config.RAW_DIR,
                    Config.SOURCE_MANIFEST_PATH,
                    **source_summary_kwargs,
                )
            else:
                self.story_summary = load_text(Config.STORY_SUMMARY_PATH)
        else:
            self.story_summary = "尚无手动配置的故事概要。"
        self.info = load_json(Config.INFO_PATH)
        self.rag = RAGEngine(
            Config.TM_PATH,
            Config.GLOSSARY_PATH,
            Config.GUIDELINES_PATH,
            api_timeout=Config.API_TIMEOUT,
            provider_data_policy=Config.PROVIDER_DATA_POLICY,
            source_root=Config.RAW_DIR,
            source_manifest_path=Config.SOURCE_MANIFEST_PATH,
            reviewed_tm_path=Config.TM_REVIEWED_PATH,
            translation_root=Config.OUTPUT_DIR,
            reviewed_tm_translation_root=(
                Config.OUTPUT_DIR
                if reviewed_tm_translation_root is None
                else reviewed_tm_translation_root
            ),
            allow_unreviewed_tm=Config.ALLOW_UNREVIEWED_TM,
            require_reviewed_glossary=Config.REQUIRE_REVIEWED_GLOSSARY,
            expected_book_bundle=Config.EXPECTED_BOOK_BUNDLE,
            require_full_book_coverage=Config.REQUIRE_REVIEWED_GLOSSARY,
            source_input_root=source_input_root,
            source_input_map=source_input_map,
        )

    @staticmethod
    def _stage_digest(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            payload = value.encode("utf-8")
        else:
            payload = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _record_stage(
        self,
        name: str,
        *,
        status: str,
        input_value: Any = None,
        output_value: Any = None,
        model: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        record = {
            "status": status,
            "input_sha256": self._stage_digest(input_value),
            "output_sha256": self._stage_digest(output_value),
        }
        if model is not None:
            record["model"] = model
        if metadata:
            record["metadata"] = metadata
        self._stage_trace[name] = record

    def _begin_stage_attempt(
        self,
        name: str,
        *,
        input_value: Any,
        model: str,
        metadata: Optional[dict] = None,
    ) -> dict:
        if not isinstance(getattr(self, "_stage_trace", None), dict):
            self._stage_trace = {}
        attempts = self._stage_trace.setdefault(name, [])
        attempt_metadata = dict(metadata or {})
        attempt_metadata.setdefault("attempt", len(attempts) + 1)
        attempt = {
            "status": "running",
            "input_sha256": self._stage_digest(input_value),
            "output_sha256": None,
            "model": model,
            "metadata": attempt_metadata,
        }
        attempts.append(attempt)
        return attempt

    def _finish_stage_attempt(
        self,
        attempt: dict,
        *,
        status: str,
        output_value: Any = None,
        metadata: Optional[dict] = None,
    ) -> None:
        attempt["status"] = status
        attempt["output_sha256"] = self._stage_digest(output_value)
        if metadata:
            attempt.setdefault("metadata", {}).update(metadata)

    def _stage_report_path(self, spec: ChapterSpec) -> Optional[Path]:
        if not Config.REQUIRE_REVIEWED_PUBLICATION:
            return None
        run_root = Path(Config.OUTPUT_DIR).resolve(strict=True).parent
        reports_root = run_root / "StageReports"
        if reports_root.is_symlink():
            raise ValueError("Stage report directory cannot be a symbolic link.")
        digest = hashlib.sha256(spec.tm_key.encode("utf-8")).hexdigest()[:32]
        return reports_root / f"episode-{digest}.json"

    def _write_stage_report(
        self,
        spec: ChapterSpec,
        *,
        status: str,
        failure_stage: Optional[str] = None,
        error_type: Optional[str] = None,
        recovery_reason: Optional[str] = None,
    ) -> None:
        report_path = self._stage_report_path(spec)
        if report_path is None:
            return
        existing_attempts = self._load_stage_report_attempts(
            spec,
            report_path,
        )
        attempt = {
            "attempt": len(existing_attempts) + 1,
            "status": status,
            "stages": self._stage_trace,
        }
        if failure_stage is not None:
            attempt["failure_stage"] = failure_stage
        if error_type is not None:
            attempt["error_type"] = error_type
        if recovery_reason is not None:
            attempt["recovery_reason"] = recovery_reason
        payload = {
            "schema_version": 1,
            "run_id": Config.TRANSLATION_RUN_ID,
            "work_id": Config.EXPECTED_BOOK_BUNDLE.get("work_id")
            if isinstance(Config.EXPECTED_BOOK_BUNDLE, dict)
            else None,
            "episode": {
                "raw_file": spec.raw_file,
                "translation_file": spec.translation_file,
                "tm_key": spec.tm_key,
                "position": spec.chapter_position,
                "source_version_id": spec.source_version_id,
                "source_input_file": spec.source_input_file,
                "source_sha256": spec.source_sha256,
            },
            "attempts": [*existing_attempts, attempt],
        }
        write_text_atomically(
            str(report_path),
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )

    def _load_stage_report_attempts(
        self,
        spec: ChapterSpec,
        report_path: Path,
    ) -> list[dict]:
        if not report_path.exists():
            return []
        if report_path.is_symlink():
            raise ValueError("Stage report cannot be a symbolic link.")
        if report_path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("Stage report exceeds the supported size limit.")
        with open_regular_file(report_path) as stream:
            previous = json.load(stream)
        expected_episode = {
            "raw_file": spec.raw_file,
            "translation_file": spec.translation_file,
            "tm_key": spec.tm_key,
            "position": spec.chapter_position,
            "source_version_id": spec.source_version_id,
            "source_input_file": spec.source_input_file,
            "source_sha256": spec.source_sha256,
        }
        if (
            not isinstance(previous, dict)
            or previous.get("schema_version") != 1
            or previous.get("run_id") != Config.TRANSLATION_RUN_ID
            or previous.get("episode") != expected_episode
            or not isinstance(previous.get("attempts"), list)
            or any(
                not isinstance(item, dict)
                for item in previous["attempts"]
            )
        ):
            raise ValueError(
                "Existing stage report does not match this run and episode."
            )
        return previous["attempts"]

    def _ensure_recovered_stage_report(
        self, spec: ChapterSpec, *, reason: str
    ) -> None:
        if not Config.REQUIRE_REVIEWED_PUBLICATION:
            return
        report_path = self._stage_report_path(spec)
        if report_path is None:
            return
        attempts = self._load_stage_report_attempts(spec, report_path)
        if any(
            item.get("status") in {"completed", "recovered"}
            for item in attempts
        ):
            return
        self._stage_trace = {}
        self._write_stage_report(
            spec,
            status="recovered",
            recovery_reason=reason,
        )

    def _get_agent_instruction(self, agent_dir: str) -> str:
        # 1. Custom or legacy lookup inside the project workspace directory
        skill_path = os.path.join(Config.WORKSPACE_DIR, agent_dir, "SKILL.md")
        if os.path.exists(skill_path):
            with open(skill_path, 'r', encoding='utf-8') as f:
                return f.read().strip()
                
        path = os.path.join(Config.WORKSPACE_DIR, agent_dir, "ai_studio_code.py")
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    match = re.search(r"system_instruction.*?text\s*=\s*['\"]{3}(.*?)['\"]{3}", content, re.DOTALL)
                    if match:
                        return match.group(1).strip()
                    match = re.search(r"system_instruction\s*=\s*['\"]{3}(.*?)['\"]{3}", content, re.DOTALL)
                    if match:
                        return match.group(1).strip()
                    match = re.search(r"system_instruction.*?text\s*=\s*['\"](.*?)['\"]", content, re.DOTALL)
                    if match:
                        return match.group(1).strip()
            except Exception:
                pass
                
        # 2. Modern generic lookup
        prompt_map = {
            "初译 Agent": "translator_skill.md",
            "逻辑审计者（校对 Agent）": "proofreader_skill.md",
            "逻辑审计者": "proofreader_skill.md",
            "校对 Agent": "proofreader_skill.md",
            "潤色 Agent（情感與文風總監）": "polisher_skill.md",
            "潤色 Agent": "polisher_skill.md",
            "润色 Agent": "polisher_skill.md",
        }
        generic_filename = prompt_map.get(agent_dir)
        if generic_filename:
            # First check for project-specific custom prompts directory
            project_prompts_dir = os.path.join(Config.WORKSPACE_DIR, "prompts")
            project_prompt_path = os.path.join(project_prompts_dir, generic_filename)
            if os.path.exists(project_prompt_path):
                with open(project_prompt_path, 'r', encoding='utf-8') as f:
                    return f.read().strip()
            # If a custom override does not exist in the project, try custom filenames directly
            # e.g., custom_polisher_skill.md
            custom_prefix = "custom_" + generic_filename
            project_custom_prompt_path = os.path.join(project_prompts_dir, custom_prefix)
            if os.path.exists(project_custom_prompt_path):
                with open(project_custom_prompt_path, 'r', encoding='utf-8') as f:
                    return f.read().strip()

            # Second check for default templates in the global prompts directory
            root_dir = os.path.dirname(os.path.abspath(__file__))
            root_prompt_path = os.path.join(root_dir, "prompts", generic_filename)
            if os.path.exists(root_prompt_path):
                with open(root_prompt_path, 'r', encoding='utf-8') as f:
                    return f.read().strip()
                    
        return ""

    def _load_reviewed_chapter_knowledge(
        self, chapter_filename: str, chapter_position: Optional[float]
    ) -> dict:
        chapter_map = Config.CHAPTER_MAP
        if not isinstance(chapter_map, list):
            raise ValueError("Chapter-local knowledge requires a versioned chapter map.")
        matches = [
            item
            for item in chapter_map
            if isinstance(item, dict) and item.get("raw_file") == chapter_filename
        ]
        if len(matches) != 1:
            raise ValueError(
                "Chapter-local knowledge requires one current chapter-map entry."
            )
        chapter = matches[0]
        position = chapter.get("chapter_position")
        if (
            isinstance(position, bool)
            or not isinstance(position, int)
            or position < 1
            or chapter_position != position
        ):
            raise ValueError(
                "Chapter-local knowledge does not match the current chapter position."
            )
        source_version_id = chapter.get("source_version_id")
        source_input_file = chapter.get("source_input_file")
        source_sha256 = chapter.get("source_sha256")
        if (
            not isinstance(source_version_id, str)
            or not source_version_id
            or not isinstance(source_input_file, str)
            or not source_input_file
            or not isinstance(source_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", source_sha256)
            or not isinstance(Config.EXPECTED_BOOK_BUNDLE, dict)
            or not isinstance(
                Config.EXPECTED_BOOK_BUNDLE.get("bundle_set_sha256"),
                str,
            )
            or not re.fullmatch(
                r"[0-9a-f]{64}",
                Config.EXPECTED_BOOK_BUNDLE["bundle_set_sha256"],
            )
            or not isinstance(Config.SOURCE_MANIFEST_PATH, str)
        ):
            raise ValueError(
                "Chapter-local knowledge requires current AI bundle and source identities."
            )

        knowledge_root = Path(Config.WORKSPACE_DIR) / "Knowledge"
        drafts_root = knowledge_root / "ChapterDrafts"
        if (
            knowledge_root.is_symlink()
            or drafts_root.is_symlink()
            or not drafts_root.is_dir()
        ):
            raise ValueError("Chapter-local knowledge directory is unavailable.")
        version_key = hashlib.sha256(
            source_version_id.encode("utf-8")
        ).hexdigest()[:16]
        legacy_directory_pattern = f"episode-{position:04d}-*-{version_key}"
        bundle_key = Config.EXPECTED_BOOK_BUNDLE["bundle_set_sha256"][:16]
        directory_pattern = (
            f"{legacy_directory_pattern}-bundle-{bundle_key}"
        )
        draft_directories = list(drafts_root.glob(directory_pattern))
        if not draft_directories:
            draft_directories = list(drafts_root.glob(legacy_directory_pattern))
        if len(draft_directories) != 1:
            raise ValueError(
                "No unique chapter-local knowledge directory matches the current source."
            )
        draft_root = draft_directories[0]
        if draft_root.is_symlink() or not draft_root.is_dir():
            raise ValueError("Chapter-local knowledge path is not a regular directory.")

        source_map = {
            chapter_filename: {
                "source_version_id": source_version_id,
                "source_input_file": source_input_file,
                "source_sha256": source_sha256,
            }
        }
        summary = load_reviewed_story_summary(
            str(draft_root / "STORY_SUMMARY_reviewed.json"),
            Config.RAW_DIR,
            Config.SOURCE_MANIFEST_PATH,
            expected_sources=[
                {
                    "filename": chapter_filename,
                    "source_version_id": source_version_id,
                    "source_input_file": source_input_file,
                }
            ],
            source_input_root=Config.AI_EDITION_ROOT,
            source_input_map=source_map,
            require_book_bundle=True,
            expected_book_bundle=Config.EXPECTED_BOOK_BUNDLE,
            expected_chapter_local={
                "position": position,
                "source_file": chapter_filename,
                "source_version_id": source_version_id,
                "source_input_file": source_input_file,
                "source_sha256": source_sha256,
            },
        )

        glossary_root = resolve_child_path(
            str(draft_root),
            "Glossary_reviewed.json",
            allow_missing=True,
        )
        if glossary_root.is_symlink():
            raise ValueError("Chapter-local glossary cannot be a symbolic link.")
        chapter_terms = {}
        if glossary_root.exists():
            with open_regular_file(glossary_root, binary=True) as stream:
                glossary_bytes = stream.read(16 * 1024 * 1024 + 1)
            if len(glossary_bytes) > 16 * 1024 * 1024:
                raise ValueError("Chapter-local glossary exceeds the size limit.")
            try:
                glossary_bundle = json.loads(glossary_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("Chapter-local glossary bundle is malformed.") from exc
            if not isinstance(glossary_bundle, dict):
                raise ValueError("Chapter-local glossary bundle must be an object.")
            chapter_terms = self.rag._parse_reviewed_glossary_bundle(
                glossary_bundle
            )
            review = glossary_bundle.get("review")
            source_files = (
                review.get("source_files")
                if isinstance(review, dict)
                else None
            )
            if (
                not isinstance(source_files, list)
                or len(source_files) != 1
                or not isinstance(source_files[0], dict)
                or source_files[0].get("filename") != chapter_filename
                or source_files[0].get("source_version_id") != source_version_id
            ):
                raise ValueError(
                    "Chapter-local glossary does not match the current source."
                )
        return {"summary": summary, "terms": chapter_terms}

    async def _build_run_context(self, chapter_filename: str, raw_text: str, current_chap_num: Optional[float]) -> dict:
        chapter_knowledge = None
        if Config.REQUIRE_REVIEWED_CHAPTER_KNOWLEDGE:
            chapter_knowledge = self._load_reviewed_chapter_knowledge(
                chapter_filename, current_chap_num
            )
        guidelines = self.rag.get_partitioned_guidelines(
            chapter_filename,
            current_raw_text=raw_text,
            chapter_position=current_chap_num,
        )
        tm_matches = await self.rag.query_translation_memory(raw_text)
        tm_prompt = ""
        if tm_matches:
            tm_prompt = "Few-shot examples from translation memory:\n"
            for pair in tm_matches:
                tm_prompt += f"Raw: {pair['raw']}\nTranslated: {pair['translated']}\n---\n"
                
        glossary_matches = self.rag.get_cleaned_glossary(
            raw_text,
            additional_glossary=(
                chapter_knowledge["terms"]
                if chapter_knowledge is not None
                else None
            ),
        )
        sliced_summary = ""
        if current_chap_num is not None:
            sliced_summary = get_sliced_story_summary(self.story_summary, current_chap_num)
            
        static_ctx = f"<WORK_INFO>\n{json.dumps(self.info, indent=2, ensure_ascii=False)}\n</WORK_INFO>\n\n"
        static_ctx += f"<GUIDELINES>\n{guidelines}\n</GUIDELINES>\n\n"
        if sliced_summary:
            static_ctx += f"<STORY_SUMMARY>\n{sliced_summary}\n</STORY_SUMMARY>\n\n"
        if chapter_knowledge and chapter_knowledge["summary"]:
            static_ctx += (
                "<CHAPTER_KNOWLEDGE>\n"
                f"{chapter_knowledge['summary']}\n"
                "</CHAPTER_KNOWLEDGE>\n\n"
            )
        if tm_prompt:
            static_ctx += f"<TRANSLATION_MEMORY>\n{tm_prompt}\n</TRANSLATION_MEMORY>\n\n"
        if glossary_matches:
            glossary_str = "\n".join([f"{g['src']}->{g['dst']}" + (f" #{g['info']}" if (g.get('info') and g.get('info') != g.get('dst')) else "") for g in glossary_matches])
            static_ctx += f"<GLOSSARY>\n{glossary_str}\n</GLOSSARY>\n\n"
            
        return {
            "static_context": static_ctx,
            "glossary_matches": glossary_matches
        }


    async def _run_context_annotation(self, raw_text: str, static_context: str) -> List[Dict[str, str]]:
        annotator_instr = "你是一个日语轻小说上下文与发言人推断专家。你的任务是阅读给定的日文段落数组，推断每句话或每段的发言人，并补充省略的主语（如果有的话）。"
        
        raw_paras = split_paragraphs(raw_text)
        json_input = json.dumps([{"paragraph": p} for p in raw_paras], ensure_ascii=False, indent=2)
        
        prompt = (
            "请分析以下日文小说段落。对于每个段落，推断发言人（如果是旁白则填旁白），并简短补充省略的主语或上下文提示。\n"
            "只输出JSON对象，结构为 {\"annotated_paragraphs\":[{\"paragraph\":\"源段落原文\",\"speaker\":\"发言人\",\"context_hint\":\"上下文提示\"}]}。"
            "数组必须与输入段落等长且顺序一致；paragraph 必须逐字保留对应源段落，没有提示时 context_hint 使用空字符串。\n"
            f"输入JSON：\n```json\n{json_input}\n```"
        )
        
        annotator_schema = {
            "type": "OBJECT",
            "required": ["annotated_paragraphs"],
            "properties": {
                "annotated_paragraphs": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "paragraph": {"type": "STRING"},
                            "speaker": {"type": "STRING"},
                            "context_hint": {"type": "STRING"}
                        },
                        "required": ["paragraph", "speaker", "context_hint"]
                    }
                }
            }
        }
        
        annotator = UnifiedAgent(
            Config.PROOFREAD_MODEL, # fast model
            annotator_instr,
            response_schema=annotator_schema,
            static_context=static_context,
            data_categories=SOURCE_AND_KNOWLEDGE_CATEGORIES,
            **Config.PROOFREADER_PARAMS
        )
        
        res = await annotator.call(prompt)
        if isinstance(res, dict) and "annotated_paragraphs" in res:
            annotated = res["annotated_paragraphs"]
            try:
                require_aligned_annotations(raw_paras, annotated, "Annotation")
            except ValueError:
                logger.warning("Annotation returned invalid paragraph data; using source paragraphs.")
                return [{"paragraph": p, "speaker": "unknown", "context_hint": ""} for p in raw_paras]
            return annotated
        return [{"paragraph": p, "speaker": "unknown", "context_hint": ""} for p in raw_paras]

    async def _run_translation_phase(self, raw_text: str, static_context: str, glossary_matches: list, annotated_context: Optional[List[Dict[str, str]]] = None) -> List[str]:
        translator_instr = self._get_agent_instruction("初译 Agent")
        
        # 1. Parse raw text into JSON array of paragraphs
        raw_paras = split_paragraphs(raw_text)
        
        # 2. Build the JSON input block
        input_data = []
        if annotated_context:
            input_data = annotated_context
        else:
            input_data = [{"paragraph": p} for p in raw_paras]
            
        json_input_str = json.dumps(input_data, ensure_ascii=False, indent=2)

        prompt_prefix = ""
        if glossary_matches:
            glossary_lines = []
            for g in glossary_matches:
                src = g["src"]
                dst = g["dst"]
                info = g.get("info")
                if info and info.strip() != dst:
                    glossary_lines.append(f"{src}->{dst} #{info}")
                else:
                    glossary_lines.append(f"{src}->{dst}")
            glossary_str = "\n".join(glossary_lines)
            prompt_prefix = (
                f"根据以下术语表（可以为空）：\n{glossary_str}\n"
                f"请将以下JSON数组中的每一个段落翻译成中文，并保持严格的1:1映射。\n"
            )
        else:
            prompt_prefix = f"请将以下JSON数组中的每一个段落翻译成中文，并保持严格的1:1映射。\n"
            
        prompt = prompt_prefix + f"输入JSON：\n```json\n{json_input_str}\n```"
            
        translator_schema = {
            "type": "OBJECT",
            "required": ["translated_paragraphs"],
            "properties": {
                "translated_paragraphs": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"}
                }
            }
        }
        
        translator = UnifiedAgent(
            Config.INITIAL_MODEL,
            translator_instr,
            response_schema=translator_schema,
            static_context=static_context,
            data_categories=SOURCE_AND_KNOWLEDGE_CATEGORIES,
            **Config.TRANSLATOR_PARAMS
        )
        res = await translator.call(prompt)
        
        if isinstance(res, dict) and "translated_paragraphs" in res:
            translated = res["translated_paragraphs"]
            require_aligned_paragraphs(raw_paras, translated, "Translation")
            return translated
        raise ValueError(
            "Translation response must contain a 'translated_paragraphs' array."
        )

    def _check_quote_mismatch(self, raw_text: str, translated_text: str) -> int:
        quote_marks = ("「", "」", "『", "』")
        count_mismatch = sum(
            abs(raw_text.count(mark) - translated_text.count(mark))
            for mark in quote_marks
        )
        raw_sequence = tuple(mark for mark in raw_text if mark in quote_marks)
        translated_sequence = tuple(
            mark for mark in translated_text if mark in quote_marks
        )
        return count_mismatch or int(raw_sequence != translated_sequence)

    async def _run_refinement_loop(self, raw_text: str, raw_translation_list: List[str], static_context: str, glossary_matches: list, annotated_context: Optional[List[Dict[str, str]]] = None) -> List[str]:
        self._active_refinement_stage = "proofreading"
        proofread_instr = self._get_agent_instruction("逻辑审计者（校对 Agent）")
        polish_instr = self._get_agent_instruction("潤色 Agent（情感與文風總監）")
        formal_quality_gate = Config.REQUIRE_REVIEWED_PUBLICATION
        
        proofread_schema = {
            "type": "OBJECT",
            "required": ["severity", "critique", "corrected_text"],
            "properties": {
                "severity": {"type": "STRING", "enum": ["none", "minor", "severe"]},
                "critique": {"type": "STRING"},
                "corrected_text": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"}
                }
            }
        }
        
        raw_paras = split_paragraphs(raw_text)
        current_translation = raw_translation_list
        require_aligned_paragraphs(raw_paras, current_translation, "Initial translation")
        
        max_retries = 2
        for attempt in range(max_retries + 1):
            self._active_refinement_stage = "proofreading"
            proofreader = UnifiedAgent(
                Config.PROOFREAD_MODEL,
                proofread_instr,
                response_schema=proofread_schema,
                static_context=static_context,
                data_categories=FULL_TRANSLATION_CATEGORIES,
                **Config.PROOFREADER_PARAMS,
            )
            
            proofread_input = [{"raw": rp, "translated": tp} for rp, tp in zip(raw_paras, current_translation)]
            json_input = json.dumps(proofread_input, ensure_ascii=False, indent=2)
            proofread_prompt = f"请检查以下段落翻译，返回严重程度、评估意见和修正后的翻译数组（1:1映射）：\n```json\n{json_input}\n```"

            proofread_attempt = self._begin_stage_attempt(
                "proofreading",
                input_value=proofread_input,
                model=Config.PROOFREAD_MODEL,
                metadata={"attempt": attempt + 1},
            )
            try:
                proofread_res = await proofreader.call(proofread_prompt)
            except ResponseContractError as error:
                self._finish_stage_attempt(
                    proofread_attempt, status="failed"
                )
                logger.warning("Proofreader returned an unreadable response.")
                if formal_quality_gate:
                    raise TranslationQualityGateError(
                        "Formal translation quality gate blocked: "
                        "proofreader response could not be read."
                    ) from error
                raise
            except Exception:
                self._finish_stage_attempt(
                    proofread_attempt, status="failed"
                )
                raise
            if not isinstance(proofread_res, dict):
                self._finish_stage_attempt(
                    proofread_attempt, status="failed"
                )
                logger.warning("Proofreader returned a non-object response.")
                if formal_quality_gate:
                    raise TranslationQualityGateError(
                        "Formal translation quality gate blocked: "
                        "proofreader response was not an object."
                    )
                corrected_list = current_translation
                self._finish_stage_attempt(
                    proofread_attempt,
                    status="fallback",
                    output_value=corrected_list,
                )
                break
            required_fields = {"severity", "critique", "corrected_text"}
            severity = proofread_res.get("severity")
            critique = proofread_res.get("critique")
            corrected_list = proofread_res.get("corrected_text")
            if (
                not required_fields.issubset(proofread_res)
                or not isinstance(severity, str)
                or severity not in {"none", "minor", "severe"}
                or not isinstance(critique, str)
            ):
                self._finish_stage_attempt(
                    proofread_attempt, status="failed"
                )
                logger.warning("Proofreader returned an invalid response schema.")
                if formal_quality_gate:
                    raise TranslationQualityGateError(
                        "Formal translation quality gate blocked: "
                        "proofreader response did not match its contract."
                    )
                corrected_list = current_translation
                self._finish_stage_attempt(
                    proofread_attempt,
                    status="fallback",
                    output_value=corrected_list,
                )
                break
            try:
                require_aligned_paragraphs(raw_paras, corrected_list, "Proofreading")
            except ValueError as error:
                self._finish_stage_attempt(
                    proofread_attempt, status="failed"
                )
                logger.warning("Proofreader returned invalid paragraph data.")
                if formal_quality_gate:
                    raise TranslationQualityGateError(
                        "Formal translation quality gate blocked: "
                        "proofreading paragraph data was invalid."
                    ) from error
                corrected_list = current_translation
                self._finish_stage_attempt(
                    proofread_attempt,
                    status="fallback",
                    output_value=corrected_list,
                )
                break

            self._finish_stage_attempt(
                proofread_attempt,
                status="completed",
                output_value=corrected_list,
                metadata={"reported_severity": severity},
            )
            if severity == "severe" and Config.STRICT_REFLECTION_MODE and attempt < max_retries:
                print(
                    "Severe proofreading issues detected. "
                    f"Triggering reflection loop (Retry {attempt+1}/{max_retries})..."
                )
                # Need to update corrected_list if we trigger reflection successfully

                translator_instr = self._get_agent_instruction("初译 Agent")
                
                # Re-run translation with critique
                prompt_prefix = ""
                if glossary_matches:
                    glossary_lines = []
                    for g in glossary_matches:
                        src = g["src"]
                        dst = g["dst"]
                        info = g.get("info")
                        if info and info.strip() != dst:
                            glossary_lines.append(f"{src}->{dst} #{info}")
                        else:
                            glossary_lines.append(f"{src}->{dst}")
                    glossary_str = "\n".join(glossary_lines)
                    prompt_prefix = (
                        f"根据以下术语表（可以为空）：\n{glossary_str}\n"
                    )
                
                input_data = []
                if annotated_context:
                    input_data = annotated_context
                else:
                    input_data = [{"paragraph": p} for p in raw_paras]
                json_input_str = json.dumps(input_data, ensure_ascii=False, indent=2)
                
                reflection_prompt = prompt_prefix + f"之前的翻译被校对指出了严重问题：\n{critique}\n请你结合这些意见，重新翻译以下JSON数组中的每一个段落，并保持严格的1:1映射。\n输入JSON：\n```json\n{json_input_str}\n```"
                
                translator_schema = {
                    "type": "OBJECT",
                    "required": ["translated_paragraphs"],
                    "properties": {
                        "translated_paragraphs": {
                            "type": "ARRAY",
                            "items": {"type": "STRING"}
                        }
                    }
                }
                self._active_refinement_stage = "reflection"
                translator = UnifiedAgent(
                    Config.INITIAL_MODEL,
                    translator_instr,
                    response_schema=translator_schema,
                    static_context=static_context,
                    data_categories=FULL_TRANSLATION_CATEGORIES,
                    **Config.TRANSLATOR_PARAMS,
                )
                reflection_attempt = self._begin_stage_attempt(
                    "reflection",
                    input_value={
                        "paragraphs": input_data,
                        "critique": critique,
                    },
                    model=Config.INITIAL_MODEL,
                    metadata={"attempt": attempt + 1},
                )
                try:
                    res = await translator.call(reflection_prompt)
                    reflection_translation = res["translated_paragraphs"]
                    require_aligned_paragraphs(
                        raw_paras, reflection_translation, "Reflection translation"
                    )
                except Exception as error:
                    self._finish_stage_attempt(
                        reflection_attempt, status="failed"
                    )
                    logger.warning(
                        "Reflection retry returned invalid paragraph data."
                    )
                    if formal_quality_gate and isinstance(
                        error, (KeyError, TypeError, ValueError)
                    ):
                        raise TranslationQualityGateError(
                            "Formal translation quality gate blocked: "
                            "reflection translation response was invalid."
                        ) from error
                    if isinstance(error, (KeyError, TypeError, ValueError)):
                        self._finish_stage_attempt(
                            reflection_attempt,
                            status="fallback",
                            output_value=current_translation,
                        )
                        break
                    raise
                self._finish_stage_attempt(
                    reflection_attempt,
                    status="completed",
                    output_value=reflection_translation,
                )
                current_translation = reflection_translation
            elif severity == "severe" and formal_quality_gate:
                raise TranslationQualityGateError(
                    "Formal translation quality gate blocked: "
                    "severe proofreading issues remain."
                )
            else:
                break
                
        # Polishing Phase
        polish_schema = {
            "type": "OBJECT",
            "required": ["polished_paragraphs"],
            "properties": {
                "polished_paragraphs": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"}
                }
            }
        }
        
        self._active_refinement_stage = "polishing"
        polisher = UnifiedAgent(
            Config.STYLE_MODEL,
            polish_instr,
            response_schema=polish_schema,
            static_context=static_context,
            data_categories=FULL_TRANSLATION_CATEGORIES,
            **Config.POLISHER_PARAMS,
        )
        require_aligned_paragraphs(raw_paras, corrected_list, "Proofreading")
        polish_input = [{"raw": rp, "translated": tp} for rp, tp in zip(raw_paras, corrected_list)]
        polish_json = json.dumps(polish_input, ensure_ascii=False, indent=2)
        polish_prompt = f"请润色以下翻译（要求返回1:1映射的JSON数组）：\n```json\n{polish_json}\n```"
        polish_attempt = self._begin_stage_attempt(
            "polishing",
            input_value=polish_input,
            model=Config.STYLE_MODEL,
        )
        try:
            polish_res = await polisher.call(polish_prompt)
        except ResponseContractError as error:
            self._finish_stage_attempt(polish_attempt, status="failed")
            logger.warning("Polisher returned an unreadable response.")
            if formal_quality_gate:
                raise TranslationQualityGateError(
                    "Formal translation quality gate blocked: "
                    "polisher response could not be read."
                ) from error
            self._finish_stage_attempt(
                polish_attempt,
                status="fallback",
                output_value=corrected_list,
            )
            return corrected_list
        except Exception:
            self._finish_stage_attempt(polish_attempt, status="failed")
            raise
        if isinstance(polish_res, dict) and "polished_paragraphs" in polish_res:
            try:
                polished_paragraphs = polish_res["polished_paragraphs"]
                require_aligned_paragraphs(raw_paras, polished_paragraphs, "Polishing")
            except (TypeError, ValueError) as error:
                self._finish_stage_attempt(polish_attempt, status="failed")
                if formal_quality_gate:
                    raise TranslationQualityGateError(
                        "Formal translation quality gate blocked: "
                        "polishing paragraph data was invalid."
                    ) from error
                self._finish_stage_attempt(
                    polish_attempt,
                    status="fallback",
                    output_value=corrected_list,
                )
            else:
                self._finish_stage_attempt(
                    polish_attempt,
                    status="completed",
                    output_value=polished_paragraphs,
                )
                return polished_paragraphs
            
        if formal_quality_gate:
            if polish_attempt["status"] == "running":
                self._finish_stage_attempt(polish_attempt, status="failed")
            raise TranslationQualityGateError(
                "Formal translation quality gate blocked: "
                "polisher response did not match its contract."
            )
        if polish_attempt["status"] == "running":
            self._finish_stage_attempt(
                polish_attempt,
                status="fallback",
                output_value=corrected_list,
            )
        print("Polisher failed or returned mismatched lines. Returning proofread results.")
        return corrected_list

    async def run_chapter(self, chapter):
        if isinstance(chapter, ChapterSpec):
            spec = chapter
        elif isinstance(chapter, str):
            spec = ChapterSpec(chapter, chapter, chapter)
        else:
            raise TypeError("Chapter must be a file name or ChapterSpec.")

        os.makedirs(Config.OUTPUT_DIR, exist_ok=True)
        mapped_paths = (
            spec.raw_file != spec.translation_file
            or "/" in spec.raw_file
            or "/" in spec.translation_file
            or spec.tm_key != spec.raw_file
        )
        if mapped_paths:
            output_path = resolve_relative_path(
                Config.OUTPUT_DIR, spec.translation_file, allow_missing=True
            )
            raw_text = _read_chapter_source_text(spec, mapped_paths)
        else:
            output_path = resolve_child_path(
                Config.OUTPUT_DIR, spec.translation_file, allow_missing=True
            )
            raw_text = None

        if spec.source_version_id is not None:
            if raw_text is None:
                raw_text = _read_chapter_source_text(spec, mapped_paths)
            self._verify_chapter_source_snapshot(spec, raw_text, mapped_paths)

        pending_transaction = has_pending_chapter_transaction(
            Config.OUTPUT_DIR, spec.translation_file, spec.tm_key
        )
        if pending_transaction:
            if raw_text is None:
                raw_text = _read_chapter_source_text(spec, mapped_paths)
            self._verify_chapter_source_snapshot(spec, raw_text, mapped_paths)
            recovered = recover_chapter_translation(
                Config.OUTPUT_DIR,
                raw_text,
                spec,
                self.rag,
                self._validate_transaction_translation,
            )
            if recovered:
                try:
                    self._ensure_recovered_stage_report(
                        spec,
                        reason="committed_output_recovered",
                    )
                except Exception as error:
                    logger.exception(
                        "Failed to persist recovered stage report for %s.",
                        spec.tm_key,
                    )
                    raise RuntimeError(
                        "Formal translation stage report could not be persisted."
                    ) from error
                print(f"RECOVERED: {spec.translation_file}")
                return

        if spec.source_version_id is not None:
            if output_path.exists():
                if is_chapter_translation_committed(
                    Config.OUTPUT_DIR,
                    raw_text,
                    spec,
                    self.rag,
                ):
                    try:
                        self._ensure_recovered_stage_report(
                            spec,
                            reason="verified_output_missing_stage_report",
                        )
                    except Exception as error:
                        logger.exception(
                            "Failed to persist recovered stage report for %s.",
                            spec.tm_key,
                        )
                        raise RuntimeError(
                            "Formal translation stage report could not be persisted."
                        ) from error
                    print(f">>> Skipping verified {spec.translation_file}")
                    return
                raise FileExistsError(
                    "Existing translation output does not match the current "
                    "source version; preserving it for review."
                )

        if output_path.exists():
            tm_chapters = self.rag.tm_data.get("chapters", {})
            if (
                output_path.is_file()
                and output_path.stat().st_size > 0
                and spec.tm_key not in tm_chapters
            ):
                logger.warning(
                    "Existing output for %s has no translation-memory entry; "
                    "skipping without rebuilding TM. Check source/output alignment "
                    "before using the chapter-alignment tool to recover it.",
                    spec.translation_file,
                )
            print(f">>> Skipping {spec.translation_file}")
            return
        if raw_text is None:
            raw_text = _read_chapter_source_text(spec, mapped_paths)
        if not raw_text.strip():
            self._verify_chapter_source_snapshot(spec, raw_text, mapped_paths)
            self._stage_trace = {}
            self._record_stage(
                "source_validation",
                status="empty",
                input_value=raw_text,
                output_value="",
            )
            self._record_stage(
                "commit",
                status="running",
                input_value=raw_text,
            )
            try:
                commit_chapter_translation(
                    Config.OUTPUT_DIR,
                    raw_text,
                    spec,
                    "",
                    self.rag,
                    self._validate_transaction_translation,
                )
            except Exception as error:
                self._record_stage(
                    "commit",
                    status="failed",
                    input_value=raw_text,
                )
                try:
                    self._write_stage_report(
                        spec,
                        status="failed",
                        failure_stage="commit",
                        error_type=type(error).__name__,
                    )
                except Exception:
                    logger.exception(
                        "Failed to persist stage report for %s.", spec.tm_key
                    )
                raise
            self._record_stage(
                "commit",
                status="completed",
                input_value=raw_text,
                output_value="",
            )
            try:
                self._write_stage_report(spec, status="completed")
            except Exception as error:
                logger.exception(
                    "Failed to persist empty-source stage report for %s.",
                    spec.tm_key,
                )
                raise RuntimeError(
                    "Formal translation stage report could not be persisted."
                ) from error
            print(f"Chapter {spec.raw_file} is empty. Committed empty output.")
            return
        current_chap_num = spec.chapter_position
        if current_chap_num is None:
            current_chap_num = extract_chapter_num(spec.raw_file)
        if current_chap_num is None:
            current_chap_num = extract_chapter_num(spec.tm_key)
        
        self._stage_trace = {}
        self._active_refinement_stage = None

        def record_failure(stage: str, error: BaseException) -> None:
            try:
                self._write_stage_report(
                    spec,
                    status="failed",
                    failure_stage=stage,
                    error_type=type(error).__name__,
                )
            except Exception:
                logger.exception("Failed to persist stage report for %s.", spec.tm_key)

        try:
            ctx_data = await self._build_run_context(
                spec.raw_file, raw_text, current_chap_num
            )
        except Exception as error:
            record_failure("context", error)
            raise
        static_context = ctx_data["static_context"]
        glossary_matches = ctx_data["glossary_matches"]
        self._record_stage(
            "context",
            status="completed",
            input_value=raw_text,
            output_value=static_context,
            metadata={"glossary_match_count": len(glossary_matches)},
        )
        
        print(f"[0/3] {spec.raw_file}: Annotating context...")
        try:
            annotated_context = await self._run_context_annotation(
                raw_text, static_context
            )
        except Exception as error:
            record_failure("annotation", error)
            raise
        self._record_stage(
            "annotation",
            status="completed",
            input_value=raw_text,
            output_value=annotated_context,
            model=Config.PROOFREAD_MODEL,
        )

        print(f"[1/3] {spec.raw_file}: Initial translation...")
        try:
            raw_translation_list = await self._run_translation_phase(
                raw_text, static_context, glossary_matches, annotated_context
            )
        except Exception as error:
            record_failure("translation", error)
            raise
        if not raw_translation_list:
            error = RuntimeError(
                f"FAILED: {spec.raw_file}: Initial translator returned empty results."
            )
            record_failure("translation", error)
            raise error
        self._record_stage(
            "translation",
            status="completed",
            input_value=raw_text,
            output_value=raw_translation_list,
            model=Config.INITIAL_MODEL,
        )
            
        print(f"[2/3 & 3/3] {spec.raw_file}: Proofread & Polish...")
        try:
            final_list = await self._run_refinement_loop(
                raw_text,
                raw_translation_list,
                static_context,
                glossary_matches,
                annotated_context,
            )
        except TranslationQualityGateError as error:
            error.chapter_position = (
                current_chap_num
                if isinstance(current_chap_num, int)
                and not isinstance(current_chap_num, bool)
                else None
            )
            record_failure(
                getattr(self, "_active_refinement_stage", None)
                or "proofreading_polishing",
                error,
            )
            raise
        except Exception as error:
            record_failure(
                getattr(self, "_active_refinement_stage", None)
                or "proofreading_polishing",
                error,
            )
            raise
        self._active_refinement_stage = None
        
        if final_list:
            raw_paras = split_paragraphs(raw_text)
            try:
                self._validate_final_paragraphs(raw_paras, final_list)
                final_text = "\n\n".join(final_list)
                self._verify_chapter_source_snapshot(spec, raw_text, mapped_paths)
                commit_chapter_translation(
                    Config.OUTPUT_DIR,
                    raw_text,
                    spec,
                    final_text,
                    self.rag,
                    self._validate_transaction_translation,
                )
            except Exception as error:
                record_failure("commit", error)
                raise
            self._record_stage(
                "commit",
                status="completed",
                input_value=final_list,
                output_value=final_text,
            )
            try:
                self._write_stage_report(spec, status="completed")
            except Exception as error:
                logger.exception("Failed to persist stage report for %s.", spec.tm_key)
                raise RuntimeError(
                    "Formal translation stage report could not be persisted."
                ) from error
            print(f"SUCCESS: {spec.translation_file}")
        else:
            error = RuntimeError(
                f"FAILED: {spec.raw_file}: Refinement returned empty results."
            )
            record_failure("polishing", error)
            raise error

    def _validate_final_paragraphs(self, raw_paras, translated_paras):
        require_aligned_paragraphs(raw_paras, translated_paras, "Final translation")
        for index, (raw_paragraph, translated_paragraph) in enumerate(
            zip(raw_paras, translated_paras), start=1
        ):
            mismatch = self._check_quote_mismatch(
                raw_paragraph, translated_paragraph
            )
            if mismatch:
                raise ValueError(
                    f"Final translation changed Japanese quote marks in "
                    f"paragraph {index} (difference: {mismatch})."
                )

    def _validate_transaction_translation(self, raw_text, translation_text):
        raw_paras = split_paragraphs(raw_text)
        translated_paras = split_paragraphs(translation_text)
        self._validate_final_paragraphs(raw_paras, translated_paras)
        if "\n\n".join(translated_paras) != translation_text:
            raise ValueError("Chapter transaction translation is not normalized.")

    def _verify_chapter_source_snapshot(self, spec, raw_text, mapped_paths):
        current_text = _read_chapter_source_text(spec, mapped_paths)
        if current_text != raw_text:
            raise ValueError(
                f"Source chapter {spec.raw_file} changed during processing."
            )

        if spec.source_version_id is None:
            return
        if not Config.SOURCE_MANIFEST_PATH:
            raise ValueError(
                "A source manifest is required to verify the chapter version."
            )
        manifest_path = resolve_relative_path(
            Config.RAW_DIR,
            Config.SOURCE_MANIFEST_PATH,
        )
        manifest = load_manifest(manifest_path)
        artifact = (
            verify_current_normalized_source_metadata(
                manifest,
                spec.source_version_id,
            )
            if spec.source_input_file is not None
            else verify_current_normalized_source(
                Config.RAW_DIR,
                manifest,
                spec.source_version_id,
            )
        )
        if (
            artifact["kind"] != "normalized_source"
            or artifact["relative_path"] != spec.raw_file
        ):
            raise ValueError(
                "Source version no longer matches the configured chapter."
            )
        if (
            spec.source_sha256 is not None
            and artifact["content_sha256"] != spec.source_sha256
        ):
            raise ValueError(
                "Source version hash no longer matches the configured chapter."
            )

    async def run_all(self):
        validate_provider_configuration()
        chapters = get_chapter_specs(
            Config.RAW_DIR,
            Config.OUTPUT_DIR,
            Config.CHAPTER_MAP,
            Config.SOURCE_MANIFEST_PATH,
            source_input_root=Config.AI_EDITION_ROOT,
        )
        if not chapters:
            raise RuntimeError(
                f"No Markdown chapters found in raw directory: {Config.RAW_DIR}"
            )
        if Config.REQUIRE_REVIEWED_CHAPTER_KNOWLEDGE:
            os.makedirs(Config.OUTPUT_DIR, exist_ok=True)
            self._preflight_reviewed_chapter_knowledge(chapters)
        print(f"Starting pipeline for {len(chapters)} chapters...")
        
        for i, chapter in enumerate(chapters):
            chapter_name = (
                chapter.raw_file if isinstance(chapter, ChapterSpec) else chapter
            )
            print(
                f"\n>>> Processing Chapter {i+1}/{len(chapters)}: "
                f"{chapter_name}"
            )
            await self.run_chapter(chapter)
            
        print("\nPipeline complete!")

    def _preflight_reviewed_chapter_knowledge(self, chapters) -> None:
        for chapter in chapters:
            if not isinstance(chapter, ChapterSpec):
                raise ValueError(
                    "Chapter-local knowledge requires a versioned chapter map."
                )
            mapped_paths = (
                chapter.raw_file != chapter.translation_file
                or "/" in chapter.raw_file
                or "/" in chapter.translation_file
                or chapter.tm_key != chapter.raw_file
            )
            if mapped_paths:
                output_path = resolve_relative_path(
                    Config.OUTPUT_DIR,
                    chapter.translation_file,
                    allow_missing=True,
                )
            else:
                output_path = resolve_child_path(
                    Config.OUTPUT_DIR,
                    chapter.translation_file,
                    allow_missing=True,
                )

            if output_path.exists():
                continue

            raw_text = _read_chapter_source_text(chapter, mapped_paths)
            if not raw_text.strip():
                continue

            position = chapter.chapter_position
            if position is None:
                position = extract_chapter_num(chapter.raw_file)
            if position is None:
                position = extract_chapter_num(chapter.tm_key)
            self._load_reviewed_chapter_knowledge(
                chapter.raw_file,
                position,
            )

if __name__ == "__main__":
    Config.load_config()
    pipeline = TranslationPipeline()
    asyncio.run(pipeline.run_all())
