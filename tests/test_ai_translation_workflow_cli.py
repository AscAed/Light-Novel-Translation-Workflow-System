import asyncio
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import AsyncMock, patch

from scripts.run_ai_translation_workflow import main


class AITranslationWorkflowCliTests(unittest.TestCase):
    def _args(self):
        return [
            "--project",
            "synthetic-project",
            "--run-directory",
            "Workflow/Runs/run-1",
            "--episode-id",
            "episode-1",
            "--review-policy-file",
            "review-policy.json",
        ]

    def test_success_loads_config_runs_preflight_and_prints_json(self):
        expected_report = {
            "status": "published",
            "episode_id": "episode-1",
            "candidate_revision": 1,
        }
        output = io.StringIO()
        errors = io.StringIO()
        with (
            patch(
                "scripts.run_ai_translation_workflow.Config.load_config"
            ) as load_config,
            patch(
                "scripts.run_ai_translation_workflow."
                "validate_final_review_provider_configuration"
            ) as validate_reviewer,
            patch(
                "scripts.run_ai_translation_workflow."
                "validate_translation_rework_provider_configuration"
            ) as validate_reworker,
            patch(
                "scripts.run_ai_translation_workflow.run_ai_translation_workflow",
                new_callable=AsyncMock,
                return_value=expected_report,
            ) as run_workflow,
            redirect_stdout(output),
            redirect_stderr(errors),
        ):
            exit_code = main(self._args())

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue()), expected_report)
        self.assertEqual(errors.getvalue(), "")
        load_config.assert_called_once_with(
            project="synthetic-project",
            config_file=None,
        )
        validate_reviewer.assert_called_once_with()
        validate_reworker.assert_called_once_with()
        run_workflow.assert_awaited_once_with(
            "Workflow/Runs/run-1",
            "episode-1",
            review_policy_file="review-policy.json",
            max_review_text_chars=64_000,
            max_rework_text_chars=64_000,
            max_rework_attempts=None,
        )

    def test_reviewer_preflight_failure_does_not_start_workflow_or_leak_error(self):
        output = io.StringIO()
        errors = io.StringIO()
        with (
            patch(
                "scripts.run_ai_translation_workflow.Config.load_config"
            ) as load_config,
            patch(
                "scripts.run_ai_translation_workflow."
                "validate_final_review_provider_configuration",
                side_effect=RuntimeError("sensitive endpoint detail"),
            ) as validate_reviewer,
            patch(
                "scripts.run_ai_translation_workflow."
                "validate_translation_rework_provider_configuration"
            ) as validate_reworker,
            patch(
                "scripts.run_ai_translation_workflow.run_ai_translation_workflow",
                new_callable=AsyncMock,
            ) as run_workflow,
            redirect_stdout(output),
            redirect_stderr(errors),
        ):
            exit_code = main(self._args())

        self.assertEqual(exit_code, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(
            errors.getvalue(),
            "ERROR: AI translation workflow refused (RuntimeError).\n",
        )
        self.assertNotIn("sensitive endpoint detail", errors.getvalue())
        load_config.assert_called_once_with(
            project="synthetic-project",
            config_file=None,
        )
        validate_reviewer.assert_called_once_with()
        validate_reworker.assert_not_called()
        run_workflow.assert_not_awaited()

    def test_rework_preflight_failure_does_not_start_workflow(self):
        output = io.StringIO()
        errors = io.StringIO()
        with (
            patch(
                "scripts.run_ai_translation_workflow.Config.load_config"
            ) as load_config,
            patch(
                "scripts.run_ai_translation_workflow."
                "validate_final_review_provider_configuration"
            ) as validate_reviewer,
            patch(
                "scripts.run_ai_translation_workflow."
                "validate_translation_rework_provider_configuration",
                side_effect=ValueError("sensitive authorization detail"),
            ) as validate_reworker,
            patch(
                "scripts.run_ai_translation_workflow.run_ai_translation_workflow",
                new_callable=AsyncMock,
            ) as run_workflow,
            redirect_stdout(output),
            redirect_stderr(errors),
        ):
            exit_code = main(self._args())

        self.assertEqual(exit_code, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(
            errors.getvalue(),
            "ERROR: AI translation workflow refused (ValueError).\n",
        )
        self.assertNotIn("sensitive authorization detail", errors.getvalue())
        load_config.assert_called_once_with(
            project="synthetic-project",
            config_file=None,
        )
        validate_reviewer.assert_called_once_with()
        validate_reworker.assert_called_once_with()
        run_workflow.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
