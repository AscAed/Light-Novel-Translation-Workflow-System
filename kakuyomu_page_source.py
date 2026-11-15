"""Explicit, robots-aware Kakuyomu episode-page source adapter."""

import hashlib
import json
import math
import os
import re
import time
import urllib.error
import urllib.robotparser
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from source_ingestion import (
    ArchiveLimitExceeded,
    CatalogPage,
    EpisodeMetadata,
    FetchedEpisode,
    SourceAccessDenied,
    SourceRateLimited,
    SourceUnavailable,
)


DEFAULT_MAX_PAGE_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_EPISODE_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_CATALOG_BYTES = 128 * 1024 * 1024
DEFAULT_MAX_EPISODES = 1000
MIN_REQUEST_DELAY_SECONDS = 1.5
DEFAULT_REQUEST_DELAY_SECONDS = 2.0
MAX_REQUEST_DELAY_SECONDS = 3.0
DEFAULT_HTTP_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_ROBOTS_BYTES = 512 * 1024
PARSER_VERSION = "kakuyomu-visible-text-v4"
WORK_CATALOG_PARSER_VERSION = "kakuyomu-apollo-toc-v1"
USER_AGENT = "LightNovelTranslationWorkflowSystem/0.1"
_EPISODE_PATH = re.compile(r"/works/([0-9]+)/episodes/([0-9]+)\Z")
_WORK_PATH = re.compile(r"/works/([0-9]+)\Z")
_BODY_CLASSES = frozenset({"widget-episodeBody", "js-episode-body"})
_BLOCK_TAGS = frozenset(
    {"article", "blockquote", "div", "h1", "h2", "h3", "li", "p", "section"}
)
_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)
_SUPPRESSED_TAGS = frozenset({"noscript", "script", "style", "svg"})


@dataclass(frozen=True)
class KakuyomuEpisodePage:
    metadata: EpisodeMetadata
    page_url: str


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


class _KakuyomuRequestClient:
    def __init__(
        self,
        *,
        opener=None,
        request_delay_seconds=DEFAULT_REQUEST_DELAY_SECONDS,
        timeout_seconds=DEFAULT_HTTP_TIMEOUT_SECONDS,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        if (
            isinstance(request_delay_seconds, bool)
            or not isinstance(request_delay_seconds, (int, float))
            or not math.isfinite(request_delay_seconds)
            or not MIN_REQUEST_DELAY_SECONDS
            <= request_delay_seconds
            <= MAX_REQUEST_DELAY_SECONDS
        ):
            raise ValueError(
                "Kakuyomu request delay must be between 1.5 and 3 seconds."
            )
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("Kakuyomu timeout must be a positive finite number.")
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler(),
            _NoRedirectHandler(),
        )
        self.request_delay_seconds = float(request_delay_seconds)
        self.timeout_seconds = float(timeout_seconds)
        self._sleep = sleep
        self._clock = clock
        self._last_request_at = None

    def request(self, url: str, *, max_bytes: int, accept: str) -> tuple[bytes, str]:
        if self._last_request_at is not None:
            wait_seconds = self.request_delay_seconds - (
                self._clock() - self._last_request_at
            )
            if wait_seconds > 0:
                self._sleep(wait_seconds)
        self._last_request_at = self._clock()
        request = urllib.request.Request(
            url,
            headers={
                "Accept": accept,
                "Accept-Encoding": "identity",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with self.opener.open(
                request, timeout=self.timeout_seconds
            ) as response:
                status = response.getcode()
                if status != 200 or response.geturl() != url:
                    raise SourceAccessDenied(
                        "Kakuyomu returned a non-canonical response."
                    )
                content_length = response.headers.get("Content-Length")
                if content_length and content_length.isdecimal():
                    if int(content_length) > max_bytes:
                        raise ValueError("Kakuyomu response exceeds the byte limit.")
                content_type = response.headers.get("Content-Type", "")
                if accept == "text/html" and not content_type.lower().startswith(
                    "text/html"
                ):
                    raise ValueError("Kakuyomu response is not HTML.")
                payload = response.read(max_bytes + 1)
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            if status == 429:
                raise SourceRateLimited("Kakuyomu rate limited the request.") from None
            if status in {401, 403, 404, 410, 451} or 300 <= status < 400:
                raise SourceAccessDenied(
                    "Kakuyomu refused the requested page."
                ) from None
            if status >= 500:
                raise SourceUnavailable("Kakuyomu is temporarily unavailable.") from None
            raise ValueError("Kakuyomu request failed.") from None
        except urllib.error.URLError:
            raise SourceUnavailable("Kakuyomu request failed.") from None
        if len(payload) > max_bytes:
            raise ValueError("Kakuyomu response exceeds the byte limit.")
        return payload, content_type


class _NextDataParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.script_count = 0
        self._capturing = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == "__NEXT_DATA__":
            self.script_count += 1
            self._capturing = True

    def handle_data(self, data):
        if self._capturing:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._capturing:
            self._capturing = False


class _EpisodePageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.body_parts = []
        self.title_parts = []
        self.body_count = 0
        self.title_count = 0
        self._body_stack = []
        self._title_stack = []

    @staticmethod
    def _classes(attrs):
        return set(dict(attrs).get("class", "").split())

    @staticmethod
    def _pop_to_matching(stack, tag):
        for index in range(len(stack) - 1, -1, -1):
            if stack[index][0] == tag:
                removed = stack[index:]
                del stack[index:]
                return removed
        return []

    @staticmethod
    def _append_boundary(parts, boundary):
        if parts and not parts[-1].endswith(boundary):
            parts.append(boundary)

    def handle_starttag(self, tag, attrs):
        classes = self._classes(attrs)
        body_started = False
        title_started = False

        if not self._body_stack and classes.intersection(_BODY_CLASSES):
            self.body_count += 1
            if self.body_count > 1:
                raise ValueError("Kakuyomu page has multiple episode-body regions.")
            self._body_stack.append((tag, tag in _SUPPRESSED_TAGS, None))
            body_started = True
        elif self._body_stack and tag not in _VOID_TAGS:
            if tag in _BLOCK_TAGS:
                self._append_boundary(self.body_parts, "\n\n")
            if tag == "br":
                self.body_parts.append("\n")
            marker = None
            if tag == "ruby":
                self.body_parts.append("｜")
                marker = "ruby"
            elif tag == "rt":
                self.body_parts.append("《")
                marker = "reading"
            elif tag == "em" and "emphasisDots" in classes:
                self.body_parts.append("｜")
                marker = "emphasis"
            self._body_stack.append(
                (tag, tag in _SUPPRESSED_TAGS or tag == "rp", marker)
            )

        if not self._title_stack and "widget-episodeTitle" in classes:
            self.title_count += 1
            if self.title_count > 1:
                raise ValueError("Kakuyomu page has multiple episode-title regions.")
            self._title_stack.append((tag, tag in _SUPPRESSED_TAGS, None))
            title_started = True
        elif self._title_stack and tag not in _VOID_TAGS:
            self._title_stack.append(
                (tag, tag in _SUPPRESSED_TAGS or tag == "rp", None)
            )

        if self._body_stack and not body_started and tag == "br":
            self.body_parts.append("\n")
        if self._title_stack and not title_started and tag == "br":
            self.title_parts.append(" ")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self._body_stack and tag in _BLOCK_TAGS:
            self._append_boundary(self.body_parts, "\n\n")
        if self._body_stack:
            removed = self._pop_to_matching(self._body_stack, tag)
            for _, _, marker in reversed(removed):
                if marker == "reading":
                    self.body_parts.append("》")
                elif marker == "emphasis":
                    self.body_parts.append("《・・・》")
        if self._title_stack:
            self._pop_to_matching(self._title_stack, tag)

    def handle_data(self, data):
        if self._body_stack and not any(
            suppressed for _, suppressed, _ in self._body_stack
        ):
            self.body_parts.append(data)
        if self._title_stack and not any(
            suppressed for _, suppressed, _ in self._title_stack
        ):
            self.title_parts.append(data)

    def extracted_title(self):
        return _normalize_title("".join(self.title_parts))

    def extracted_body(self):
        text = "".join(self.body_parts).replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip(" \t\r\n")


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _positive_limit(name: str, value) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer.")


def _validate_page_url(page_url: str, work_id: str, episode_id: str) -> None:
    if not isinstance(page_url, str):
        raise ValueError("Kakuyomu page URL must be text.")
    parsed = urlsplit(page_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "kakuyomu.jp"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Kakuyomu page URL must be a canonical HTTPS episode URL.")
    match = _EPISODE_PATH.fullmatch(parsed.path)
    if not match or match.group(1) != work_id or match.group(2) != episode_id:
        raise ValueError("Kakuyomu page URL does not match its catalog identity.")


def _decode_response(payload: bytes, content_type: str) -> str:
    match = re.search(r"(?:^|;)\s*charset=([^;\s]+)", content_type, re.IGNORECASE)
    encoding = match.group(1).strip("\"'") if match else "utf-8"
    try:
        return payload.decode(encoding)
    except (LookupError, UnicodeError) as exc:
        raise ValueError("Kakuyomu response could not be decoded.") from exc


def _parse_robots(robots_bytes: bytes) -> urllib.robotparser.RobotFileParser:
    robots_text = _decode_response(robots_bytes, "text/plain; charset=utf-8")
    if not re.search(r"(?im)^\s*user-agent\s*:", robots_text):
        raise SourceAccessDenied("Kakuyomu robots.txt is empty or invalid.")
    robots = urllib.robotparser.RobotFileParser("https://kakuyomu.jp/robots.txt")
    robots.parse(robots_text.splitlines())
    return robots


def _resolve_apollo_reference(state, value, expected_type: str) -> dict:
    if not isinstance(value, dict) or set(value) != {"__ref"}:
        raise ValueError("Kakuyomu work catalog contains an invalid reference.")
    reference = value["__ref"]
    if not isinstance(reference, str) or not reference.startswith(
        expected_type + ":"
    ):
        raise ValueError("Kakuyomu work catalog contains an unsupported entry.")
    entity = state.get(reference)
    if not isinstance(entity, dict) or entity.get("__typename") != expected_type:
        raise ValueError("Kakuyomu work catalog contains a missing entity.")
    return entity


class KakuyomuWorkCatalog:
    def __init__(
        self,
        work_id: str,
        work_url: str,
        episodes: tuple[KakuyomuEpisodePage, ...],
        source_fingerprint: str,
        robots_bytes: bytes,
        http_client: _KakuyomuRequestClient,
    ):
        self.work_id = work_id
        self.work_url = work_url
        self.episodes = episodes
        self.source_fingerprint = source_fingerprint
        self._robots_bytes = robots_bytes
        self._http_client = http_client

    def create_page_adapter(self, **options):
        return KakuyomuPageAdapter(
            self.work_id,
            self.episodes,
            _http_client=self._http_client,
            _robots_bytes=self._robots_bytes,
            _discovery_fingerprint=self.source_fingerprint,
            **options,
        )


def discover_kakuyomu_work_catalog(
    work_url: str,
    *,
    max_work_page_bytes: int = DEFAULT_MAX_PAGE_BYTES,
    max_episodes: int = DEFAULT_MAX_EPISODES,
    request_delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS,
    timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
    opener=None,
    sleep=time.sleep,
    clock=time.monotonic,
) -> KakuyomuWorkCatalog:
    if not isinstance(work_url, str):
        raise ValueError("Kakuyomu work URL must be text.")
    parsed_url = urlsplit(work_url)
    if (
        parsed_url.scheme != "https"
        or parsed_url.hostname != "kakuyomu.jp"
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.port is not None
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise ValueError("Kakuyomu work URL must be a canonical HTTPS URL.")
    match = _WORK_PATH.fullmatch(parsed_url.path)
    if not match:
        raise ValueError("Kakuyomu work URL must identify a work homepage.")
    work_id = match.group(1)
    _positive_limit("max_work_page_bytes", max_work_page_bytes)
    _positive_limit("max_episodes", max_episodes)

    http_client = _KakuyomuRequestClient(
        opener=opener,
        request_delay_seconds=request_delay_seconds,
        timeout_seconds=timeout_seconds,
        sleep=sleep,
        clock=clock,
    )
    robots_bytes, _ = http_client.request(
        "https://kakuyomu.jp/robots.txt",
        max_bytes=DEFAULT_MAX_ROBOTS_BYTES,
        accept="text/plain",
    )
    robots = _parse_robots(robots_bytes)
    if not robots.can_fetch(USER_AGENT, work_url):
        raise SourceAccessDenied(
            "Kakuyomu robots.txt disallows the work homepage."
        )

    work_page_bytes, content_type = http_client.request(
        work_url,
        max_bytes=max_work_page_bytes,
        accept="text/html",
    )
    work_page_text = _decode_response(work_page_bytes, content_type)
    parser = _NextDataParser()
    parser.feed(work_page_text)
    parser.close()
    if parser.script_count != 1:
        raise ValueError("Kakuyomu work page has no unique Next.js data block.")
    try:
        next_data = json.loads("".join(parser.parts))
    except (RecursionError, json.JSONDecodeError) as exc:
        raise ValueError("Kakuyomu work page data is invalid.") from exc

    try:
        page_props = next_data["props"]["pageProps"]
        apollo_state = page_props["__APOLLO_STATE__"]
    except (KeyError, TypeError) as exc:
        raise ValueError("Kakuyomu work page has no catalog data.") from exc
    if not isinstance(apollo_state, dict):
        raise ValueError("Kakuyomu work page catalog data is invalid.")
    work = apollo_state.get(f"Work:{work_id}")
    if (
        not isinstance(work, dict)
        or work.get("__typename") != "Work"
        or work.get("id") != work_id
    ):
        raise ValueError("Kakuyomu work page does not match the requested work.")

    public_episode_count = work.get("publicEpisodeCount")
    if (
        isinstance(public_episode_count, bool)
        or not isinstance(public_episode_count, int)
        or public_episode_count < 1
    ):
        raise ValueError("Kakuyomu work page has an invalid public episode count.")
    if public_episode_count > max_episodes:
        raise ValueError("Kakuyomu work exceeds the configured episode limit.")
    toc_groups = work.get("tableOfContentsV2")
    if not isinstance(toc_groups, list) or not toc_groups:
        raise ValueError("Kakuyomu work page has no table of contents.")

    episodes = []
    seen_ids = set()
    for group_reference in toc_groups:
        group = _resolve_apollo_reference(
            apollo_state, group_reference, "TableOfContentsChapter"
        )
        episode_references = group.get("episodeUnions")
        if not isinstance(episode_references, list):
            raise ValueError("Kakuyomu table of contents is invalid.")
        for episode_reference in episode_references:
            episode = _resolve_apollo_reference(
                apollo_state, episode_reference, "Episode"
            )
            episode_id = episode.get("id")
            title = episode.get("title")
            if (
                not isinstance(episode_id, str)
                or not episode_id.isascii()
                or not episode_id.isdecimal()
                or not isinstance(title, str)
                or not _normalize_title(title)
                or any(ord(character) < 32 for character in title)
            ):
                raise ValueError("Kakuyomu work page has invalid episode metadata.")
            if episode_id in seen_ids:
                raise ValueError("Kakuyomu table of contents repeats an episode.")
            seen_ids.add(episode_id)
            page_url = (
                f"https://kakuyomu.jp/works/{work_id}/episodes/{episode_id}"
            )
            episodes.append(
                KakuyomuEpisodePage(
                    EpisodeMetadata(
                        episode_id,
                        _normalize_title(title),
                        len(episodes) + 1,
                        page_url,
                    ),
                    page_url,
                )
            )
    if len(episodes) != public_episode_count:
        raise ValueError(
            "Kakuyomu table of contents does not match the public episode count."
        )
    for episode in episodes:
        if not robots.can_fetch(USER_AGENT, episode.page_url):
            raise SourceAccessDenied(
                "Kakuyomu robots.txt disallows a discovered episode URL."
            )

    catalog_fingerprint = hashlib.sha256(
        json.dumps(
            {
                "parser": WORK_CATALOG_PARSER_VERSION,
                "work_id": work_id,
                "robots_sha256": hashlib.sha256(robots_bytes).hexdigest(),
                "public_episode_count": public_episode_count,
                "episodes": [
                    {
                        "episode_id": episode.metadata.episode_id,
                        "position": episode.metadata.position,
                        "title": episode.metadata.title,
                        "page_url": episode.page_url,
                    }
                    for episode in episodes
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return KakuyomuWorkCatalog(
        work_id,
        work_url,
        tuple(episodes),
        catalog_fingerprint,
        robots_bytes,
        http_client,
    )


def save_discovered_work_catalog(
    source_root: str | Path,
    relative_path: str,
    work_id: str,
    episodes,
) -> Path:
    from utils import open_regular_file, resolve_relative_path

    source_root_path = Path(source_root).resolve(strict=True)
    if not source_root_path.is_dir():
        raise ValueError("Kakuyomu source root must be a directory.")
    output_path = resolve_relative_path(
        str(source_root_path),
        relative_path,
        allow_missing=True,
    )
    catalog = {
        "schema_version": 1,
        "work_id": work_id,
        "episodes": [
            {
                "episode_id": episode.metadata.episode_id,
                "position": episode.metadata.position,
                "page_url": episode.page_url,
                "title": episode.metadata.title,
            }
            for episode in episodes
        ],
    }
    payload = (
        json.dumps(
            catalog,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    if output_path.exists():
        with open_regular_file(output_path, binary=True) as existing_file:
            if existing_file.read(len(payload) + 1) == payload:
                return output_path
        raise FileExistsError(
            "The discovered catalog already exists with different contents."
        )

    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    descriptor = os.open(output_path, flags, 0o600)
    try:
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("Could not write the discovered catalog.")
            remaining = remaining[written:]
    finally:
        os.close(descriptor)
    return output_path


class KakuyomuPageAdapter:
    """Fetch an ordered episode catalog one page at a time."""

    def __init__(
        self,
        work_id: str,
        episodes,
        *,
        page_size: int = 50,
        max_page_bytes: int = DEFAULT_MAX_PAGE_BYTES,
        max_episode_bytes: int = DEFAULT_MAX_EPISODE_BYTES,
        max_catalog_bytes: int = DEFAULT_MAX_CATALOG_BYTES,
        max_episodes: int = DEFAULT_MAX_EPISODES,
        request_delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS,
        timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
        opener=None,
        sleep=time.sleep,
        clock=time.monotonic,
        _http_client: _KakuyomuRequestClient | None = None,
        _robots_bytes: bytes | None = None,
        _discovery_fingerprint: str | None = None,
    ):
        if (
            not isinstance(work_id, str)
            or not work_id.isascii()
            or not work_id.isdecimal()
        ):
            raise ValueError("Kakuyomu work_id must be a numeric identifier.")
        if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < 1:
            raise ValueError("Kakuyomu page_size must be a positive integer.")
        for name, value in (
            ("max_page_bytes", max_page_bytes),
            ("max_episode_bytes", max_episode_bytes),
            ("max_catalog_bytes", max_catalog_bytes),
            ("max_episodes", max_episodes),
        ):
            _positive_limit(name, value)
        if not isinstance(episodes, (list, tuple)) or not episodes:
            raise ValueError("Kakuyomu page catalog must not be empty.")
        if len(episodes) > max_episodes:
            raise ValueError("Kakuyomu page catalog exceeds the episode limit.")
        if _robots_bytes is not None and not isinstance(_robots_bytes, bytes):
            raise ValueError("Kakuyomu robots snapshot must be bytes.")
        if _discovery_fingerprint is not None and (
            not isinstance(_discovery_fingerprint, str)
            or not re.fullmatch(r"[0-9a-f]{64}", _discovery_fingerprint)
        ):
            raise ValueError("Kakuyomu discovery fingerprint is invalid.")

        self.work_id = work_id
        self.page_size = page_size
        self.max_page_bytes = max_page_bytes
        self.max_episode_bytes = max_episode_bytes
        self.max_catalog_bytes = max_catalog_bytes
        self.max_episodes = max_episodes
        self._http_client = _http_client or _KakuyomuRequestClient(
            opener=opener,
            request_delay_seconds=request_delay_seconds,
            timeout_seconds=timeout_seconds,
            sleep=sleep,
            clock=clock,
        )
        self._discovery_fingerprint = _discovery_fingerprint

        normalized = []
        seen_ids = set()
        seen_positions = set()
        for item in episodes:
            if not isinstance(item, KakuyomuEpisodePage):
                raise ValueError("Kakuyomu page catalog contains an invalid entry.")
            metadata = item.metadata
            if (
                not isinstance(metadata, EpisodeMetadata)
                or not isinstance(metadata.episode_id, str)
                or not metadata.episode_id.isascii()
                or not metadata.episode_id.isdecimal()
                or not isinstance(metadata.title, str)
                or metadata.title.strip() != metadata.title
                or any(ord(character) < 32 for character in metadata.title)
                or isinstance(metadata.position, bool)
                or not isinstance(metadata.position, int)
                or metadata.position < 1
            ):
                raise ValueError("Kakuyomu page catalog has invalid episode metadata.")
            if metadata.episode_id in seen_ids:
                raise ValueError("Kakuyomu page catalog repeats an episode_id.")
            if metadata.position in seen_positions:
                raise ValueError("Kakuyomu page catalog repeats a position.")
            _validate_page_url(item.page_url, work_id, metadata.episode_id)
            if metadata.source_ref not in (None, item.page_url):
                raise ValueError("Kakuyomu source_ref must match its page URL.")
            normalized.append(
                KakuyomuEpisodePage(
                    EpisodeMetadata(
                        metadata.episode_id,
                        metadata.title,
                        metadata.position,
                        item.page_url,
                    ),
                    item.page_url,
                )
            )
            seen_ids.add(metadata.episode_id)
            seen_positions.add(metadata.position)
        if [item.metadata.position for item in normalized] != sorted(seen_positions):
            raise ValueError("Kakuyomu page catalog must be in ascending position order.")
        self.episodes = tuple(normalized)

        if _robots_bytes is None:
            robots_bytes, _ = self._request(
                "https://kakuyomu.jp/robots.txt",
                max_bytes=DEFAULT_MAX_ROBOTS_BYTES,
                accept="text/plain",
            )
        else:
            robots_bytes = _robots_bytes
        robots = _parse_robots(robots_bytes)
        for item in self.episodes:
            if not robots.can_fetch(USER_AGENT, item.page_url):
                raise SourceAccessDenied(
                    "Kakuyomu robots.txt disallows an episode URL."
                )

        self._robots_bytes = robots_bytes
        self._catalog_bytes = 0
        fingerprint_bytes = json.dumps(
            {
                "adapter": PARSER_VERSION,
                "work_id": work_id,
                "robots_sha256": hashlib.sha256(robots_bytes).hexdigest(),
                "work_catalog_fingerprint": self._discovery_fingerprint,
                "episodes": [
                    {
                        "episode_id": item.metadata.episode_id,
                        "title": item.metadata.title,
                        "position": item.metadata.position,
                        "page_url": item.page_url,
                    }
                    for item in self.episodes
                ],
                "limits": {
                    "max_page_bytes": max_page_bytes,
                    "max_episode_bytes": max_episode_bytes,
                    "max_catalog_bytes": max_catalog_bytes,
                    "max_episodes": max_episodes,
                },
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.source_fingerprint = hashlib.sha256(fingerprint_bytes).hexdigest()

    def set_completed_catalog_bytes(self, value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("Completed catalog byte count must be non-negative.")
        self._catalog_bytes = value

    def _request(
        self, url: str, *, max_bytes: int, accept: str
    ) -> tuple[bytes, str]:
        return self._http_client.request(
            url,
            max_bytes=max_bytes,
            accept=accept,
        )

    def list_episodes(self, cursor: str | None) -> CatalogPage:
        if cursor is None:
            offset = 0
        elif (
            not isinstance(cursor, str)
            or not cursor.isascii()
            or not cursor.isdecimal()
            or cursor.startswith("0")
        ):
            raise ValueError("Kakuyomu cursor must be a canonical positive offset.")
        else:
            offset = int(cursor)
        if offset < 0 or (offset >= len(self.episodes) and offset != 0):
            raise ValueError("Kakuyomu cursor is out of range.")
        end = min(offset + self.page_size, len(self.episodes))
        next_cursor = str(end) if end < len(self.episodes) else None
        return CatalogPage(
            tuple(item.metadata for item in self.episodes[offset:end]),
            next_cursor,
        )

    def fetch_episode(self, episode_id: str) -> FetchedEpisode:
        item = next(
            (
                episode
                for episode in self.episodes
                if episode.metadata.episode_id == episode_id
            ),
            None,
        )
        if item is None:
            raise ValueError(
                "Episode is not present in the Kakuyomu catalog."
            )
        page_bytes, page_content_type = self._request(
            item.page_url,
            max_bytes=self.max_page_bytes,
            accept="text/html",
        )
        page_text = _decode_response(page_bytes, page_content_type)
        parser = _EpisodePageParser()
        parser.feed(page_text)
        parser.close()
        if (
            parser.body_count != 1
            or parser.title_count != 1
            or parser._body_stack
            or parser._title_stack
        ):
            raise ValueError(
                "Kakuyomu page is missing its unique episode title or body."
            )
        page_title = parser.extracted_title()
        if item.metadata.title and page_title != _normalize_title(item.metadata.title):
            raise ValueError("Kakuyomu page title does not match the catalog.")
        content = parser.extracted_body().encode("utf-8")
        if not content:
            raise ValueError("Kakuyomu episode body is empty.")
        if len(content) > self.max_episode_bytes:
            raise ValueError("Kakuyomu episode exceeds the configured byte limit.")
        if self._catalog_bytes + len(content) > self.max_catalog_bytes:
            raise ArchiveLimitExceeded(
                "Kakuyomu episodes exceed the configured byte limit."
            )
        self._catalog_bytes += len(content)
        return FetchedEpisode(
            EpisodeMetadata(
                episode_id,
                page_title,
                item.metadata.position,
                item.page_url,
            ),
            content,
        )
