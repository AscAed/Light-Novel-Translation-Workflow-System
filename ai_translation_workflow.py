"""Resumable review, bounded rework, and publication orchestration."""

from pathlib import Path

from ai_translation_review import _review_translation_candidate_locked
from ai_translation_rework import _generate_translation_rework_candidate_locked
from translation_review import _load_run, _run_episode
from translation_review_state import (
    _lock_episode_workflow,
    load_review_decision_chain,
    load_review_resolution_chain,
)


def _history_entry(result: dict) -> dict:
    return {
        key: result[key]
        for key in (
            "status",
            "candidate_revision",
            "candidate_sha256",
            "decision_sha256",
            "review_report_relative_path",
            "issue_codes_by_stage",
            "final_review_gate",
        )
        if key in result
    }


def _candidate_file(run_root: Path, decision: dict) -> Path | None:
    if decision["candidate_revision"] == 0:
        return None
    return run_root / Path(decision["candidate_relative_path"])


async def _run_ai_translation_workflow_locked(
    run_directory: str | Path,
    episode_id: str,
    *,
    review_policy_file: str | Path,
    assessor=None,
    generator=None,
    reviewer_model: str | None = None,
    rework_model: str | None = None,
    max_review_text_chars: int = 64_000,
    max_rework_text_chars: int = 64_000,
    max_rework_attempts: int | None = None,
) -> dict:
    """Run or resume one bounded AI review/rework chain."""
    run_root, run, _ = _load_run(run_directory)
    episode = _run_episode(run, episode_id)
    chain = load_review_decision_chain(
        run_root,
        episode_id=episode_id,
        expected_run_id=run["run_id"],
        expected_work_id=run["work_id"],
        expected_source_version_id=episode["source_version_id"],
        expected_source_sha256=episode["source_sha256"],
    )
    history = []
    rework_history = []

    if chain:
        latest = chain[-1]
        status = latest["transition"]["status"]
        if status == "passed":
            result = await _review_translation_candidate_locked(
                run_root,
                episode_id,
                review_policy_file=review_policy_file,
                candidate_file=_candidate_file(run_root, latest),
                assessor=assessor,
                reviewer_model=reviewer_model,
                max_review_text_chars=max_review_text_chars,
                max_rework_attempts=max_rework_attempts,
            )
            return {**result, "review_history": [_history_entry(result)]}
        if status == "needs_human":
            resolutions = load_review_resolution_chain(
                run_root,
                episode_id=episode_id,
            )
            resolution = next(
                (
                    item
                    for item in reversed(resolutions)
                    if item["decision_sha256"] == latest["decision_sha256"]
                ),
                None,
            )
            if resolution is None or resolution["action"] != "increase_budget":
                return {
                    "status": "needs_human",
                    "episode_id": episode_id,
                    "candidate_revision": latest["candidate_revision"],
                    "candidate_sha256": latest["candidate_sha256"],
                    "decision_sha256": latest["decision_sha256"],
                    "transition": latest["transition"],
                    "resolution_action": (
                        resolution["action"] if resolution is not None else None
                    ),
                    "review_history": [],
                }
        elif status != "rework":
            raise ValueError("The latest review decision is not resumable.")

        candidate = await _generate_translation_rework_candidate_locked(
            run_root,
            episode_id,
            review_policy_file=review_policy_file,
            generator=generator,
            rework_model=rework_model,
            max_rework_text_chars=max_rework_text_chars,
        )
        rework_history.append(
            {
                key: candidate[key]
                for key in (
                    "candidate_revision",
                    "candidate_relative_path",
                    "candidate_sha256",
                    "rework_report_relative_path",
                    "origin",
                )
            }
        )
        result = await _review_translation_candidate_locked(
            run_root,
            episode_id,
            review_policy_file=review_policy_file,
            candidate_file=run_root / candidate["candidate_relative_path"],
            assessor=assessor,
            reviewer_model=reviewer_model,
            max_review_text_chars=max_review_text_chars,
            max_rework_attempts=max_rework_attempts,
        )
        history.append(_history_entry(result))
    else:
        result = await _review_translation_candidate_locked(
            run_root,
            episode_id,
            review_policy_file=review_policy_file,
            assessor=assessor,
            reviewer_model=reviewer_model,
            max_review_text_chars=max_review_text_chars,
            max_rework_attempts=max_rework_attempts,
        )
        history.append(_history_entry(result))

    while result["status"] == "rework":
        candidate = await _generate_translation_rework_candidate_locked(
            run_root,
            episode_id,
            review_policy_file=review_policy_file,
            generator=generator,
            rework_model=rework_model,
            max_rework_text_chars=max_rework_text_chars,
        )
        rework_history.append(
            {
                key: candidate[key]
                for key in (
                    "candidate_revision",
                    "candidate_relative_path",
                    "candidate_sha256",
                    "rework_report_relative_path",
                    "origin",
                )
            }
        )
        result = await _review_translation_candidate_locked(
            run_root,
            episode_id,
            review_policy_file=review_policy_file,
            candidate_file=run_root / candidate["candidate_relative_path"],
            assessor=assessor,
            reviewer_model=reviewer_model,
            max_review_text_chars=max_review_text_chars,
        )
        history.append(_history_entry(result))

    return {
        **result,
        "review_history": history,
        "rework_history": rework_history,
    }


async def run_ai_translation_workflow(
    run_directory: str | Path,
    episode_id: str,
    *,
    review_policy_file: str | Path,
    assessor=None,
    generator=None,
    reviewer_model: str | None = None,
    rework_model: str | None = None,
    max_review_text_chars: int = 64_000,
    max_rework_text_chars: int = 64_000,
    max_rework_attempts: int | None = None,
) -> dict:
    """Run or resume the complete workflow under one episode lock."""
    run_root, run, _ = _load_run(run_directory)
    _run_episode(run, episode_id)
    async with _lock_episode_workflow(run_root, episode_id):
        return await _run_ai_translation_workflow_locked(
            run_root,
            episode_id,
            review_policy_file=review_policy_file,
            assessor=assessor,
            generator=generator,
            reviewer_model=reviewer_model,
            rework_model=rework_model,
            max_review_text_chars=max_review_text_chars,
            max_rework_text_chars=max_rework_text_chars,
            max_rework_attempts=max_rework_attempts,
        )
