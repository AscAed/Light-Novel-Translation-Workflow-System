"""Prepare EPUB catalog metadata from a verified approved translation artifact."""

from copy import deepcopy

from metadata_translation_publication import verify_metadata_translation_artifact


def create_epub_metadata_catalog(
    epub_catalog: dict,
    artifact: dict,
    plan: dict,
    candidate: dict,
    review: dict,
    current_source_snapshot: dict,
    current_field_statuses: dict,
    current_field_sources: dict,
) -> tuple[dict, dict]:
    """Overlay approved title translations and return their provenance."""
    verify_metadata_translation_artifact(
        artifact,
        plan,
        candidate,
        review,
        artifact.get("source_snapshot"),
    )
    if not isinstance(epub_catalog, dict):
        raise ValueError("EPUB catalog must be a JSON object.")
    if (
        epub_catalog.get("work_id") != artifact["work_id"]
        or epub_catalog.get("language") != artifact["target_locale"]
    ):
        raise ValueError("EPUB catalog work ID or language differs from metadata.")
    if not isinstance(current_field_statuses, dict):
        raise ValueError("Current metadata field freshness is invalid.")
    if not isinstance(current_field_sources, dict):
        raise ValueError("Current metadata field lineage is invalid.")

    approved = {}
    artifact_fields = {}
    for field in artifact["fields"]:
        artifact_fields[field["field_id"]] = field
        if field["status"] == "approved":
            value = field["translation_value"]
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Approved metadata translation is empty.")
            approved[field["field_id"]] = value

    title = approved.get("work.title")
    chapters = epub_catalog.get("chapters")
    if title is None or not isinstance(chapters, list) or not chapters:
        raise ValueError("Approved work title or EPUB chapters are missing.")

    overlaid = deepcopy(epub_catalog)
    overlaid["title"] = title
    for chapter in overlaid["chapters"]:
        if not isinstance(chapter, dict):
            raise ValueError("EPUB catalog contains an invalid chapter.")
        episode_id = chapter.get("episode_id")
        if not isinstance(episode_id, str) or not episode_id:
            raise ValueError("EPUB chapter has no valid episode ID.")
        field_id = f"episode.{episode_id}.title"
        episode_title = approved.get(field_id)
        if episode_title is None:
            raise ValueError(
                "EPUB chapter has no approved current metadata translation."
            )
        if current_field_statuses.get(field_id) != "current":
            raise ValueError("Metadata field is stale for EPUB consumption.")
        current_source = current_field_sources.get(field_id)
        if (
            not isinstance(current_source, dict)
            or current_source.get("source_sha256")
            != artifact_fields[field_id]["source_sha256"]
            or not isinstance(current_source.get("source_version_id"), str)
        ):
            raise ValueError("Current metadata field lineage does not match approval.")
        chapter["title"] = episode_title
    if current_field_statuses.get("work.title") != "current":
        raise ValueError("Metadata field is stale for EPUB consumption.")
    current_work_source = current_field_sources.get("work.title")
    if (
        not isinstance(current_work_source, dict)
        or current_work_source.get("source_sha256")
        != artifact_fields["work.title"]["source_sha256"]
        or not isinstance(current_work_source.get("source_version_id"), str)
    ):
        raise ValueError("Current metadata field lineage does not match approval.")

    provenance = {
        "artifact_sha256": artifact["artifact_sha256"],
        "plan_sha256": artifact["plan_sha256"],
        "candidate_sha256": artifact["candidate_sha256"],
        "review_sha256": artifact["review_sha256"],
        "quality_rules_sha256": artifact["quality_rules_sha256"],
        "artifact_source_snapshot": dict(artifact["source_snapshot"]),
        "current_source_snapshot": dict(current_source_snapshot),
        "field_lineage": {
            field_id: dict(current_field_sources[field_id])
            for field_id in {"work.title"}
            | {f"episode.{chapter['episode_id']}.title" for chapter in chapters}
        },
    }
    return overlaid, provenance
