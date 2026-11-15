"""Build immutable, explicitly scoped EPUB candidates from Markdown chapters."""

import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit, urlunsplit

from source_ingestion import source_artifact_id
from source_manifest import (
    latest_artifacts_by_kind,
    parse_manifest_bytes,
    verify_manifest_artifact,
)
from utils import open_regular_file, resolve_relative_path

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z")
_PANDOC_VERSION = re.compile(r"^pandoc\s+([^\s]+)", re.IGNORECASE)
_IMAGE_MARKUP = re.compile(r"!\[|<img\b", re.IGNORECASE)
_NETWORK_RESOURCE_MARKUP = re.compile(
    r"<\s*(?:audio|video|source|track|iframe|object|embed|link|style)\b"
    r"|<\s*[A-Za-z][^>]*\b(?:src|srcset|poster|data)\s*="
    r"|<\s*[A-Za-z][^>]*\bstyle\s*=",
    re.IGNORECASE | re.DOTALL,
)
_INLINE_LINK_DESTINATION = re.compile(
    r"(?<!!)\]\(\s*(?:<([^>\n]*)>|([^\s)]+))",
    re.DOTALL,
)
_REFERENCE_LINK_DESTINATION = re.compile(
    r"(?m)^\s{0,3}\[(?!\^)[^\]]+\]:\s*(?:<([^>]+)>|(\S+))"
)
_HTML_HREF = re.compile(
    r"\bhref\s*=\s*(['\"])(.*?)\1",
    re.IGNORECASE | re.DOTALL,
)
_FOOTNOTE_DEFINITION = re.compile(r"(?m)^\s{0,3}\[\^([^\]]+)\]:")
_FOOTNOTE_REFERENCE = re.compile(r"\[\^([^\]]+)\](?!:)")
_MAX_CATALOG_BYTES = 1024 * 1024
_MAX_BYTE_LIMIT = 1024 * 1024 * 1024


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Catalog contains a duplicate JSON key.")
        result[key] = value
    return result


def _text(value, field, maximum=512):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"Catalog field {field} must be non-empty plain text.")
    return value


def _positive_limit(value, field, *, maximum=None):
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or (maximum is not None and value > maximum)
    ):
        raise ValueError(f"{field} is outside its supported positive range.")
    return value


def get_pandoc_version(executable="pandoc", timeout_seconds=10):
    result = subprocess.run(
        [executable, "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError("Could not read the Pandoc version.")
    match = _PANDOC_VERSION.match(result.stdout.splitlines()[0])
    if not match:
        raise RuntimeError("Pandoc returned an unrecognized version.")
    return match.group(1)


def _read_catalog(root, relative_path):
    path = resolve_relative_path(root, relative_path)
    with open_regular_file(path, binary=True) as stream:
        raw = stream.read(_MAX_CATALOG_BYTES + 1)
    if len(raw) > _MAX_CATALOG_BYTES:
        raise ValueError("Chapter catalog exceeds the 1 MiB limit.")
    try:
        catalog = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Chapter catalog is not valid UTF-8 JSON.") from exc
    if not isinstance(catalog, dict):
        raise ValueError("Chapter catalog must be a JSON object.")
    return catalog


def _validate_catalog(catalog):
    required = {
        "schema_version",
        "work_id",
        "build_id",
        "expected_pandoc_version",
        "title",
        "author",
        "language",
        "identifier",
        "chapters",
    }
    if set(catalog) != required:
        raise ValueError("Chapter catalog has missing or unknown fields.")
    if (
        isinstance(catalog["schema_version"], bool)
        or catalog["schema_version"] != 1
    ):
        raise ValueError("Unsupported chapter catalog schema.")

    for field in ("work_id", "build_id"):
        value = catalog[field]
        if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
            raise ValueError(f"Catalog field {field} is not a safe identifier.")

    metadata = {
        field: _text(catalog[field], field)
        for field in ("expected_pandoc_version", "title", "author", "language", "identifier")
    }
    chapters = catalog["chapters"]
    if not isinstance(chapters, list) or not chapters or len(chapters) > 10000:
        raise ValueError("Catalog must contain between 1 and 10000 chapters.")

    seen_ids = set()
    seen_paths = set()
    previous_position = 0
    normalized = []
    chapter_fields = {
        "episode_id",
        "position",
        "title",
        "translation_path",
        "source_version_id",
    }
    for chapter in chapters:
        if not isinstance(chapter, dict) or set(chapter) != chapter_fields:
            raise ValueError("Chapter entry has missing or unknown fields.")
        episode_id = _text(chapter["episode_id"], "episode_id")
        position = chapter["position"]
        if (
            isinstance(position, bool)
            or not isinstance(position, int)
            or position <= previous_position
        ):
            raise ValueError("Chapter positions must be positive and strictly increasing.")
        previous_position = position
        title = _text(chapter["title"], "chapter title")
        translation_path = _text(chapter["translation_path"], "translation_path")
        source_version_id = _text(chapter["source_version_id"], "source_version_id")
        path_key = translation_path.casefold()
        if episode_id in seen_ids or path_key in seen_paths:
            raise ValueError("Chapter IDs and paths must be unique.")
        if Path(translation_path).suffix.lower() != ".md":
            raise ValueError("Translation inputs must be Markdown files.")
        seen_ids.add(episode_id)
        seen_paths.add(path_key)
        normalized.append(
            {
                "episode_id": episode_id,
                "position": position,
                "title": title,
                "translation_path": translation_path,
                "source_version_id": source_version_id,
            }
        )

    return metadata, normalized


def _read_chapter(root, chapter, max_chapter_bytes):
    path = resolve_relative_path(root, chapter["translation_path"])
    with open_regular_file(path, binary=True) as stream:
        content = stream.read(max_chapter_bytes + 1)
    if len(content) > max_chapter_bytes:
        raise ValueError("A translation chapter exceeds its byte limit.")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("A translation chapter is not valid UTF-8.") from exc
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if first_line != f"# {chapter['title']}":
        raise ValueError("Each chapter must start with its catalog-matched H1 title.")
    if _IMAGE_MARKUP.search(text):
        raise ValueError("Image markup is not supported by this candidate builder.")
    if _NETWORK_RESOURCE_MARKUP.search(text):
        raise ValueError(
            "Embedded media and resource references are not supported by this candidate builder."
        )
    return content


def _link_destinations(text):
    for pattern in (
        _INLINE_LINK_DESTINATION,
        _REFERENCE_LINK_DESTINATION,
    ):
        for match in pattern.finditer(text):
            destination = next(
                (value for value in match.groups() if value is not None), ""
            )
            if destination:
                yield destination
    for match in _HTML_HREF.finditer(text):
        if match.group(2):
            yield match.group(2)


def _uses_cross_chapter_references(chapters, chapter_texts):
    all_definitions = {}
    chapter_definitions = {}
    chapter_references = {}
    for chapter in chapters:
        episode_id = chapter["episode_id"]
        text = chapter_texts[episode_id]
        definitions = set(_FOOTNOTE_DEFINITION.findall(text))
        references = set(_FOOTNOTE_REFERENCE.findall(text))
        chapter_definitions[episode_id] = definitions
        chapter_references[episode_id] = references
        for definition in definitions:
            all_definitions.setdefault(definition, set()).add(episode_id)

    for chapter in chapters:
        episode_id = chapter["episode_id"]
        for reference in chapter_references[episode_id]:
            if (
                reference not in chapter_definitions[episode_id]
                and all_definitions.get(reference, set()) - {episode_id}
            ):
                return True

        source_path = posixpath.normpath(chapter["translation_path"])
        source_key = os.path.normcase(source_path)
        for destination in _link_destinations(chapter_texts[episode_id]):
            try:
                parsed = urlsplit(destination.strip())
            except ValueError:
                return True
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            target_path = posixpath.normpath(
                posixpath.join(
                    posixpath.dirname(source_path),
                    unquote(parsed.path),
                )
            )
            if os.path.normcase(target_path) != source_key:
                return True
    return False


def _chapter_xhtml_paths(archive, chapters):
    opf_names = [
        name
        for name in archive.namelist()
        if name.lower().endswith(".opf")
    ]
    if len(opf_names) != 1:
        raise ValueError("Pandoc output must contain one package document.")
    opf_name = opf_names[0]
    try:
        package = ET.fromstring(archive.read(opf_name))
    except ET.ParseError as exc:
        raise ValueError("Pandoc output package document is invalid.") from exc

    manifest_items = {}
    for item in package.iter():
        if _local_name(item) != "item":
            continue
        item_id = item.get("id")
        if not item_id or item_id in manifest_items:
            raise ValueError("Pandoc output package has invalid manifest IDs.")
        manifest_items[item_id] = item

    spine = next(
        (element for element in package.iter() if _local_name(element) == "spine"),
        None,
    )
    if spine is None:
        raise ValueError("Pandoc output package is missing its spine.")

    opf_directory = posixpath.dirname(opf_name)
    chapter_documents = []
    for itemref in spine:
        if _local_name(itemref) != "itemref" or itemref.get("linear") == "no":
            continue
        item = manifest_items.get(itemref.get("idref"))
        if item is None:
            raise ValueError("Pandoc output spine references a missing item.")
        properties = set(item.get("properties", "").split())
        if "nav" in properties:
            continue
        if item.get("media-type") != "application/xhtml+xml":
            raise ValueError("Pandoc output spine contains a non-XHTML chapter.")
        href = item.get("href")
        parsed_href = urlsplit(href or "")
        if (
            not parsed_href.path
            or parsed_href.scheme
            or parsed_href.netloc
            or parsed_href.query
            or parsed_href.fragment
        ):
            raise ValueError("Pandoc output chapter path is invalid.")
        decoded_href = unquote(parsed_href.path)
        if decoded_href.startswith("/") or "\\" in decoded_href:
            raise ValueError("Pandoc output chapter path is invalid.")
        document_path = posixpath.normpath(
            posixpath.join(opf_directory, decoded_href)
        )
        if document_path == ".." or document_path.startswith("../"):
            raise ValueError("Pandoc output chapter path escapes the EPUB.")
        try:
            document = ET.fromstring(archive.read(document_path))
        except (KeyError, ET.ParseError) as exc:
            raise ValueError("Pandoc output chapter document is invalid.") from exc
        body = next(
            (
                element
                for element in document.iter()
                if _local_name(element) == "body"
            ),
            None,
        )
        if (
            body is None
            or "bodymatter"
            not in body.get("{http://www.idpf.org/2007/ops}type", "").split()
        ):
            continue
        if not any(_local_name(element) == "h1" for element in document.iter()):
            raise ValueError("Pandoc output chapter is missing its H1.")
        chapter_documents.append(document_path)

    if len(chapter_documents) != len(chapters):
        raise ValueError(
            "Pandoc output does not map the selected chapters in spine order."
        )
    return {
        os.path.normcase(posixpath.normpath(chapter["translation_path"])): (
            posixpath.normpath(chapter["translation_path"]),
            name,
        )
        for chapter, name in zip(chapters, chapter_documents)
    }


def _rewrite_cross_chapter_links(epub_path, chapters):
    temporary_path = None
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{epub_path.name}.",
        suffix=".rewrite",
        dir=str(epub_path.parent),
    )
    os.close(descriptor)
    try:
        with zipfile.ZipFile(epub_path, "r") as source:
            archive_path_by_translation = _chapter_xhtml_paths(source, chapters)
            translation_by_archive = {
                archive_path: translation_path
                for translation_path, archive_path in archive_path_by_translation.values()
            }
            with zipfile.ZipFile(temporary_path, "w") as rewritten:
                for info in source.infolist():
                    content = source.read(info.filename)
                    translation_path = translation_by_archive.get(info.filename)
                    if translation_path is not None and info.filename.lower().endswith(
                        ".xhtml"
                    ):
                        document = ET.fromstring(content)
                        for element in document.iter():
                            href = element.get("href")
                            if not href:
                                continue
                            try:
                                parsed = urlsplit(href)
                            except ValueError:
                                continue
                            if parsed.scheme or parsed.netloc or not parsed.path:
                                continue
                            target_translation = posixpath.normpath(
                                posixpath.join(
                                    posixpath.dirname(translation_path),
                                    unquote(parsed.path),
                                )
                            )
                            target_chapter = archive_path_by_translation.get(
                                os.path.normcase(target_translation)
                            )
                            if target_chapter is None:
                                continue
                            _, target_archive = target_chapter
                            rewritten_path = posixpath.relpath(
                                target_archive,
                                start=posixpath.dirname(info.filename),
                            )
                            element.set(
                                "href",
                                urlunsplit(
                                    (
                                        "",
                                        "",
                                        rewritten_path,
                                        parsed.query,
                                        parsed.fragment,
                                    )
                                ),
                            )
                        content = ET.tostring(
                            document,
                            encoding="utf-8",
                            xml_declaration=True,
                        )
                    rewritten.writestr(info, content)
        os.replace(temporary_path, epub_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass


def _validate_source_versions(
    source_root,
    manifest_relative_path,
    work_id,
    chapters,
):
    root = Path(source_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Source root must be a directory.")
    manifest_path = resolve_relative_path(str(root), manifest_relative_path)
    with open_regular_file(manifest_path, binary=True) as stream:
        manifest_bytes = stream.read()
    manifest = parse_manifest_bytes(manifest_bytes)
    latest_normalized = latest_artifacts_by_kind(
        manifest, "normalized_source"
    )

    for chapter in chapters:
        expected_artifact_id = source_artifact_id(
            work_id,
            "normalized_source",
            chapter["episode_id"],
        )
        artifact = verify_manifest_artifact(
            root,
            manifest,
            chapter["source_version_id"],
        )
        if (
            artifact["kind"] != "normalized_source"
            or artifact["artifact_id"] != expected_artifact_id
        ):
            raise ValueError(
                "A source version does not match its catalog work and episode."
            )
        latest = latest_normalized.get(expected_artifact_id)
        if latest is None or latest["version_id"] != artifact["version_id"]:
            raise ValueError(
                "A source version is stale relative to the source manifest."
            )

    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    return (
        manifest_path.relative_to(root).as_posix(),
        manifest_sha256,
    )


def _local_name(element):
    return element.tag.rsplit("}", 1)[-1]


def validate_epub_structure(path):
    """Check core ZIP/OPF/XHTML structure; this is not a full EPUBCheck run."""
    with open_regular_file(path, binary=True) as stream:
        with zipfile.ZipFile(stream) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if not names or names[0] != "mimetype":
                raise ValueError("EPUB mimetype must be the first archive entry.")
            if len(names) != len(set(names)):
                raise ValueError("EPUB archive contains duplicate paths.")
            for name in names:
                member = PurePosixPath(name)
                if (
                    "\\" in name
                    or name.startswith("/")
                    or any(part in {"", ".", ".."} for part in member.parts)
                ):
                    raise ValueError("EPUB archive contains an unsafe member path.")
            if infos[0].compress_type != zipfile.ZIP_STORED:
                raise ValueError("EPUB mimetype entry must be uncompressed.")
            if archive.read("mimetype") != b"application/epub+zip":
                raise ValueError("EPUB mimetype entry has an invalid value.")
            if archive.testzip() is not None:
                raise ValueError("EPUB archive failed its CRC check.")

            container = ET.fromstring(archive.read("META-INF/container.xml"))
            rootfile = next(
                (
                    element
                    for element in container.iter()
                    if _local_name(element) == "rootfile"
                ),
                None,
            )
            package_path = rootfile.get("full-path") if rootfile is not None else None
            if not package_path or package_path not in names:
                raise ValueError("EPUB container does not reference a package document.")

            package = ET.fromstring(archive.read(package_path))
            manifest = next(
                (element for element in package if _local_name(element) == "manifest"),
                None,
            )
            spine = next(
                (element for element in package if _local_name(element) == "spine"),
                None,
            )
            if manifest is None or spine is None:
                raise ValueError("EPUB package is missing its manifest or spine.")

            package_dir = PurePosixPath(package_path).parent
            manifest_items = {}
            for item in manifest:
                if _local_name(item) != "item":
                    continue
                item_id = item.get("id")
                href = item.get("href")
                media_type = item.get("media-type")
                if not item_id or not href or not media_type or item_id in manifest_items:
                    raise ValueError("EPUB manifest contains an invalid item.")
                resolved = (package_dir / PurePosixPath(href)).as_posix()
                if (
                    resolved.startswith("../")
                    or "\\" in href
                    or resolved not in names
                ):
                    raise ValueError("EPUB manifest references a missing member.")
                manifest_items[item_id] = (resolved, media_type)

            spine_items = [
                item for item in spine if _local_name(item) == "itemref"
            ]
            if not spine_items:
                raise ValueError("EPUB spine has no readable content items.")
            for item in spine_items:
                reference = manifest_items.get(item.get("idref"))
                if not reference or reference[1] not in {
                    "application/xhtml+xml",
                    "text/html",
                }:
                    raise ValueError("EPUB spine references a non-content item.")
                if reference[1] == "application/xhtml+xml":
                    ET.fromstring(archive.read(reference[0]))
    return {
        "zip_crc": "passed",
        "container_package": "passed",
        "spine_xhtml": "passed",
        "epubcheck": "not_run",
    }


def _write_json_exclusive(path, value):
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ).encode("utf-8")
    with open(path, "xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def build_epub_candidate(
    *,
    input_root,
    catalog_relative_path,
    source_root,
    source_manifest_relative_path,
    output_root,
    max_chapter_bytes,
    max_total_bytes,
    max_output_bytes,
    pandoc_executable="pandoc",
    timeout_seconds=120,
):
    """Build a non-publishable candidate and a provenance sidecar manifest."""
    max_chapter_bytes = _positive_limit(
        max_chapter_bytes,
        "max_chapter_bytes",
        maximum=_MAX_BYTE_LIMIT,
    )
    max_total_bytes = _positive_limit(
        max_total_bytes,
        "max_total_bytes",
        maximum=_MAX_BYTE_LIMIT,
    )
    max_output_bytes = _positive_limit(
        max_output_bytes,
        "max_output_bytes",
        maximum=_MAX_BYTE_LIMIT,
    )
    timeout_seconds = _positive_limit(
        timeout_seconds,
        "timeout_seconds",
        maximum=86400,
    )

    root = Path(input_root).resolve(strict=True)
    catalog = _read_catalog(root, catalog_relative_path)
    metadata, chapters = _validate_catalog(catalog)
    (
        source_manifest_identity,
        source_manifest_sha256,
    ) = _validate_source_versions(
        source_root,
        source_manifest_relative_path,
        catalog["work_id"],
        chapters,
    )
    chapter_data = []
    chapter_snapshots = []
    chapter_texts = {}
    total_bytes = 0
    for chapter in chapters:
        content = _read_chapter(root, chapter, max_chapter_bytes)
        total_bytes += len(content)
        if total_bytes > max_total_bytes:
            raise ValueError("Selected translation chapters exceed their total byte limit.")
        chapter_data.append(
            {
                **chapter,
                "content_sha256": hashlib.sha256(content).hexdigest(),
                "content_bytes": len(content),
            }
        )
        chapter_snapshots.append(content)
        chapter_texts[chapter["episode_id"]] = content.decode("utf-8")
    file_scope = not _uses_cross_chapter_references(chapters, chapter_texts)

    pandoc_version = get_pandoc_version(pandoc_executable)
    if pandoc_version != metadata["expected_pandoc_version"]:
        raise ValueError("Installed Pandoc version does not match the catalog.")

    output_path = Path(output_root)
    output_path.mkdir(parents=True, exist_ok=True)
    if output_path.is_symlink():
        raise ValueError("Output root cannot be a symbolic link.")
    output_path = output_path.resolve(strict=True)
    work_dir = output_path / catalog["work_id"]
    work_dir.mkdir(exist_ok=True)
    if work_dir.is_symlink() or not work_dir.is_dir():
        raise ValueError("Work output path must be a regular directory.")
    target_dir = work_dir / catalog["build_id"]
    if target_dir.exists() or target_dir.is_symlink():
        raise FileExistsError("Candidate output already exists.")

    staging_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{catalog['build_id']}.",
            suffix=".staging",
            dir=work_dir,
        )
    )
    try:
        epub_path = staging_dir / "candidate.epub"
        input_dir = staging_dir / "inputs"
        input_dir.mkdir()
        pandoc_inputs = []
        for chapter, content in zip(chapters, chapter_snapshots):
            input_path = input_dir / chapter["translation_path"]
            input_path.parent.mkdir(parents=True, exist_ok=True)
            with open(input_path, "xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            pandoc_inputs.append(chapter["translation_path"])

        command = [
            pandoc_executable,
            "--from=markdown-yaml_metadata_block",
            "--to=epub3",
            *(["--file-scope"] if file_scope else []),
            "--split-level=1",
            "--toc",
            f"--metadata=title:{metadata['title']}",
            f"--metadata=author:{metadata['author']}",
            f"--metadata=lang:{metadata['language']}",
            f"--metadata=identifier:{metadata['identifier']}",
            f"--output={epub_path}",
            "--",
            *pandoc_inputs,
        ]
        result = subprocess.run(
            command,
            cwd=input_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        if result.returncode != 0 or not epub_path.is_file():
            raise RuntimeError("Pandoc failed to build the EPUB candidate.")

        _rewrite_cross_chapter_links(epub_path, chapters)
        epub_bytes = epub_path.stat().st_size
        if epub_bytes > max_output_bytes:
            raise ValueError("Generated EPUB exceeds its output byte limit.")
        validation = validate_epub_structure(epub_path)
        with open_regular_file(epub_path, binary=True) as stream:
            epub_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
        shutil.rmtree(input_dir)
        manifest = {
            "schema_version": 1,
            "artifact_status": "candidate",
            "quality_gate_status": "not_evaluated",
            "coverage_scope": "explicit_episode_selection",
            "work_id": catalog["work_id"],
            "build_id": catalog["build_id"],
            "source_manifest": {
                "relative_path": source_manifest_identity,
                "content_sha256": source_manifest_sha256,
            },
            "metadata": {
                key: metadata[key]
                for key in ("title", "author", "language", "identifier")
            },
            "pandoc": {
                "executable_name": Path(pandoc_executable).name,
                "version": pandoc_version,
                "split_level": 1,
                "file_scope": file_scope,
                "table_of_contents": True,
            },
            "chapters": chapter_data,
            "epub": {
                "relative_path": "candidate.epub",
                "content_bytes": epub_bytes,
                "content_sha256": epub_sha256,
            },
            "validation": validation,
        }
        _write_json_exclusive(staging_dir / "build.json", manifest)
        os.rename(staging_dir, target_dir)
        staging_dir = None
        return {
            "status": "candidate",
            "relative_directory": f"{catalog['work_id']}/{catalog['build_id']}",
            "chapter_count": len(chapters),
            "content_sha256": epub_sha256,
            "pandoc_version": pandoc_version,
            "validation": validation,
        }
    finally:
        if staging_dir is not None:
            resolved_stage = staging_dir.resolve(strict=False)
            if (
                not staging_dir.is_symlink()
                and resolved_stage.parent == work_dir.resolve(strict=True)
                and staging_dir.name.startswith(f".{catalog['build_id']}.")
            ):
                shutil.rmtree(staging_dir, ignore_errors=True)
