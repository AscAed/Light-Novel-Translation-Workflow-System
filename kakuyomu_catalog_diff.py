"""Compare validated Kakuyomu catalog snapshots without reading episode bodies."""


def _episode_map(snapshot):
    episodes = snapshot.get("episodes")
    if not isinstance(episodes, tuple) or not episodes:
        raise ValueError("Kakuyomu catalog snapshot has no episodes.")
    result = {}
    positions = []
    for episode in episodes:
        metadata = episode.metadata
        episode_id = metadata.episode_id
        position = metadata.position
        expected_url = (
            f"https://kakuyomu.jp/works/{snapshot['work_id']}/episodes/"
            f"{episode_id}"
        )
        if (
            not isinstance(episode_id, str)
            or not episode_id.isascii()
            or not episode_id.isdecimal()
            or isinstance(position, bool)
            or not isinstance(position, int)
            or position < 1
            or not isinstance(metadata.title, str)
            or episode.page_url != expected_url
        ):
            raise ValueError("Kakuyomu catalog snapshot has invalid episode metadata.")
        if episode_id in result:
            raise ValueError("Kakuyomu catalog snapshot repeats an episode.")
        result[episode_id] = episode
        positions.append(position)
    if positions != sorted(set(positions)):
        raise ValueError("Kakuyomu catalog snapshot positions are invalid.")
    return result


def _chapter_maps(snapshot):
    assignments = {}
    metadata = {}
    groups = {}
    for chapter in snapshot["chapters"]:
        group_id = chapter["group_id"]
        if group_id in groups:
            raise ValueError("Kakuyomu catalog snapshot repeats a chapter group.")
        groups[group_id] = chapter
        metadata[group_id] = (
            chapter["chapter_id"],
            chapter["title"],
            chapter["level"],
        )
        for episode_id in chapter["episode_ids"]:
            if episode_id in assignments:
                raise ValueError("Kakuyomu catalog repeats a grouped episode.")
            assignments[episode_id] = group_id
    return assignments, metadata, groups


def _compare_chapter_groups(previous_groups, current_groups):
    changes = []
    unchanged_count = 0
    for group_id in sorted(previous_groups.keys() | current_groups.keys()):
        previous = previous_groups.get(group_id)
        current = current_groups.get(group_id)
        if previous is None:
            change_names = ["added"]
            change = "added"
        elif current is None:
            change_names = ["removed"]
            change = "removed"
        else:
            change_names = []
            if (
                previous["chapter_id"],
                previous["title"],
                previous["level"],
            ) != (
                current["chapter_id"],
                current["title"],
                current["level"],
            ):
                change_names.append("chapter_metadata_changed")
            if (
                previous["position_start"],
                previous["position_end"],
            ) != (
                current["position_start"],
                current["position_end"],
            ):
                change_names.append("position_range_changed")
            if previous["episode_ids"] != current["episode_ids"]:
                change_names.append("episode_membership_changed")
            if change_names:
                change = "updated"
            else:
                unchanged_count += 1
                continue

        changes.append(
            {
                "group_id": group_id,
                "change": change,
                "previous_position_start": (
                    previous["position_start"] if previous is not None else None
                ),
                "previous_position_end": (
                    previous["position_end"] if previous is not None else None
                ),
                "previous_episode_count": (
                    len(previous["episode_ids"]) if previous is not None else 0
                ),
                "current_position_start": (
                    current["position_start"] if current is not None else None
                ),
                "current_position_end": (
                    current["position_end"] if current is not None else None
                ),
                "current_episode_count": (
                    len(current["episode_ids"]) if current is not None else 0
                ),
                "changes": change_names,
            }
        )
    counts = {
        "added": sum(item["change"] == "added" for item in changes),
        "removed": sum(item["change"] == "removed" for item in changes),
        "updated": sum(item["change"] == "updated" for item in changes),
        "unchanged": unchanged_count,
    }
    return changes, counts


def append_only_catalog_status(previous, current):
    if previous["work_id"] != current["work_id"]:
        return {
            "append_only": False,
            "added_count": 0,
            "chapter_comparison": "unavailable",
            "issues": ["different_work"],
        }

    previous_episodes = tuple(previous["episodes"])
    current_episodes = tuple(current["episodes"])
    issues = []
    if len(current_episodes) < len(previous_episodes):
        issues.append("episode_removed")
    for index, old_episode in enumerate(previous_episodes):
        if index >= len(current_episodes):
            break
        new_episode = current_episodes[index]
        old = old_episode.metadata
        new = new_episode.metadata
        if (
            old.episode_id != new.episode_id
            or (old.title and old.title != new.title)
            or old.position != new.position
            or old_episode.page_url != new_episode.page_url
        ):
            issues.append("existing_episode_changed")
            break

    chapter_comparison = (
        "available"
        if previous["schema_version"] >= 2 and current["schema_version"] >= 2
        else "unavailable_legacy_catalog"
    )
    if chapter_comparison == "available":
        previous_assignments, previous_metadata, previous_groups = _chapter_maps(
            previous
        )
        current_assignments, current_metadata, current_groups = _chapter_maps(
            current
        )
        previous_ids = {
            episode.metadata.episode_id for episode in previous_episodes
        }
        for episode_id in previous_ids:
            if previous_assignments.get(episode_id) != current_assignments.get(
                episode_id
            ):
                issues.append("existing_chapter_assignment_changed")
                break
        for group_id, old_group in previous_groups.items():
            new_group = current_groups.get(group_id)
            if new_group is None:
                issues.append("existing_chapter_removed")
                break
            if previous_metadata[group_id] != current_metadata[group_id]:
                issues.append("existing_chapter_metadata_changed")
                break
            old_ids = tuple(old_group["episode_ids"])
            new_ids = tuple(new_group["episode_ids"])
            if new_ids[: len(old_ids)] != old_ids:
                issues.append("existing_chapter_membership_changed")
                break

    return {
        "append_only": not issues,
        "added_count": max(0, len(current_episodes) - len(previous_episodes)),
        "chapter_comparison": chapter_comparison,
        "issues": issues,
    }


def exact_refresh_catalog_status(previous, current):
    if previous["work_id"] != current["work_id"]:
        return {
            "same_catalog": False,
            "episode_count": 0,
            "chapter_comparison": "unavailable",
            "issues": ["different_work"],
        }

    previous_episodes = tuple(previous["episodes"])
    current_episodes = tuple(current["episodes"])
    issues = []
    if len(previous_episodes) != len(current_episodes):
        issues.append("episode_count_changed")
    for index, old_episode in enumerate(previous_episodes):
        if index >= len(current_episodes):
            break
        new_episode = current_episodes[index]
        old = old_episode.metadata
        new = new_episode.metadata
        if (
            old.episode_id != new.episode_id
            or old.title != new.title
            or old.position != new.position
            or old.source_ref != new.source_ref
            or old_episode.page_url != new_episode.page_url
        ):
            issues.append("episode_metadata_changed")
            break

    chapter_comparison = (
        "available"
        if previous["schema_version"] >= 2 and current["schema_version"] >= 2
        else "unavailable_legacy_catalog"
    )
    if chapter_comparison == "available":
        old_chapters = tuple(
            (
                chapter["group_id"],
                chapter["chapter_id"],
                chapter["title"],
                chapter["level"],
                chapter["position_start"],
                chapter["position_end"],
                tuple(chapter["episode_ids"]),
            )
            for chapter in previous["chapters"]
        )
        new_chapters = tuple(
            (
                chapter["group_id"],
                chapter["chapter_id"],
                chapter["title"],
                chapter["level"],
                chapter["position_start"],
                chapter["position_end"],
                tuple(chapter["episode_ids"]),
            )
            for chapter in current["chapters"]
        )
        if old_chapters != new_chapters:
            issues.append("chapter_structure_changed")

    return {
        "same_catalog": not issues,
        "episode_count": len(current_episodes),
        "chapter_comparison": chapter_comparison,
        "issues": issues,
    }


def compare_catalog_snapshots(previous, current):
    if previous["work_id"] != current["work_id"]:
        raise ValueError("Kakuyomu catalog snapshots belong to different works.")
    previous_episodes = _episode_map(previous)
    current_episodes = _episode_map(current)
    compare_chapters = (
        previous["schema_version"] >= 2 and current["schema_version"] >= 2
    )
    compare_work_metadata = (
        previous["schema_version"] >= 3 and current["schema_version"] >= 3
    )
    previous_assignments, previous_chapters, previous_groups = _chapter_maps(
        previous
    )
    current_assignments, current_chapters, current_groups = _chapter_maps(current)
    if compare_chapters:
        chapter_changes, chapter_counts = _compare_chapter_groups(
            previous_groups,
            current_groups,
        )
    else:
        chapter_changes = None
        chapter_counts = None
    if compare_work_metadata:
        previous_metadata = previous["work_metadata"]
        current_metadata = current["work_metadata"]
        work_metadata_changed_fields = sorted(
            field
            for field in previous_metadata.keys() | current_metadata.keys()
            if previous_metadata.get(field) != current_metadata.get(field)
        )
    else:
        work_metadata_changed_fields = None

    changes = []
    unchanged_count = 0
    for episode_id in sorted(
        previous_episodes.keys() | current_episodes.keys(),
        key=lambda item: (
            current_episodes[item].metadata.position
            if item in current_episodes
            else previous_episodes[item].metadata.position,
            item,
        ),
    ):
        previous_episode = previous_episodes.get(episode_id)
        current_episode = current_episodes.get(episode_id)
        if previous_episode is None:
            change_names = ["added"]
            change = "added"
        elif current_episode is None:
            change_names = ["removed"]
            change = "removed"
        else:
            change_names = []
            if previous_episode.metadata.title != current_episode.metadata.title:
                change_names.append("title_changed")
            if (
                previous_episode.metadata.position
                != current_episode.metadata.position
            ):
                change_names.append("position_changed")
            if compare_chapters:
                previous_group = previous_assignments.get(episode_id)
                current_group = current_assignments.get(episode_id)
                if previous_group != current_group:
                    change_names.append("chapter_group_changed")
                elif previous_group is not None and (
                    previous_chapters.get(previous_group)
                    != current_chapters.get(current_group)
                ):
                    change_names.append("chapter_metadata_changed")
            if change_names:
                change = "updated"
            else:
                unchanged_count += 1
                continue

        changes.append(
            {
                "episode_id": episode_id,
                "change": change,
                "previous_position": (
                    previous_episode.metadata.position
                    if previous_episode is not None
                    else None
                ),
                "current_position": (
                    current_episode.metadata.position
                    if current_episode is not None
                    else None
                ),
                "changes": change_names,
            }
        )

    counts = {
        "added": sum(item["change"] == "added" for item in changes),
        "removed": sum(item["change"] == "removed" for item in changes),
        "updated": sum(item["change"] == "updated" for item in changes),
        "unchanged": unchanged_count,
    }
    return {
        "schema_version": 1,
        "work_id": current["work_id"],
        "previous_catalog_sha256": previous["sha256"],
        "current_catalog_sha256": current["sha256"],
        "append_only_compatibility": append_only_catalog_status(
            previous, current
        ),
        "episode_comparison": "id_title_position",
        "chapter_comparison": (
            "available" if compare_chapters else "unavailable_v1_snapshot"
        ),
        "chapter_counts": chapter_counts,
        "chapter_changes": chapter_changes,
        "work_metadata_comparison": (
            "available" if compare_work_metadata else "unavailable_v3_snapshot"
        ),
        "work_metadata_changed_fields": work_metadata_changed_fields,
        "counts": counts,
        "changes": changes,
    }


def create_selection_catalog(snapshot, report, selection):
    if selection not in {"added", "updated"}:
        raise ValueError("Catalog selection must be added or updated.")
    if (
        report.get("work_id") != snapshot["work_id"]
        or report.get("current_catalog_sha256") != snapshot["sha256"]
    ):
        raise ValueError("Catalog selection does not match the current snapshot.")
    selected_ids = {
        item["episode_id"]
        for item in report["changes"]
        if item["change"] == selection
    }
    if not selected_ids:
        raise ValueError(f"Catalog snapshot has no {selection} episodes.")
    episodes = [
        {
            "episode_id": episode.metadata.episode_id,
            "position": episode.metadata.position,
            "page_url": episode.page_url,
            "title": episode.metadata.title,
        }
        for episode in snapshot["episodes"]
        if episode.metadata.episode_id in selected_ids
    ]
    if len(episodes) != len(selected_ids):
        raise ValueError("Catalog diff selection does not match its snapshot.")
    return {
        "schema_version": 1,
        "work_id": snapshot["work_id"],
        "episodes": episodes,
    }
