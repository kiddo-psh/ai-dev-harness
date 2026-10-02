"""core/ci/claude-review/review-status.py (feelm test_review_status.py 이관)."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "review_status", ROOT / "core" / "ci" / "claude-review" / "review-status.py")
status = importlib.util.module_from_spec(spec)
spec.loader.exec_module(status)

SHA = "a" * 40
PIPELINE_URL = "https://gitlab.example/team/project/-/pipelines/88"
POLICY = status.common.validate_policy({"target_branch": "develop"})


def merge_request(sha=SHA, state="opened"):
    return {"iid": 7, "state": state, "target_branch": "develop",
            "source_project_id": 123, "target_project_id": 123, "sha": sha}


class ReviewStatusTests(unittest.TestCase):
    def test_accepts_only_trusted_review_context(self):
        valid = {"CI_COMMIT_BRANCH": "develop", "CI_COMMIT_REF_PROTECTED": "true",
                 "CI_ENVIRONMENT_NAME": "claude-review", "CI_PIPELINE_SOURCE": "api",
                 "CLAUDE_REVIEW_TRIGGER": "comment"}
        self.assertTrue(status.trusted_context(valid, POLICY))
        self.assertFalse(status.trusted_context(dict(valid, CI_COMMIT_BRANCH="feature"), POLICY))
        self.assertFalse(status.trusted_context(dict(valid, CLAUDE_REVIEW_TRIGGER="manual"), POLICY))
        self.assertFalse(status.trusted_context(dict(valid, CI_DEBUG_TRACE="true"), POLICY))

    def test_pipeline_url_must_match_trusted_project_and_pipeline_id(self):
        self.assertEqual(status.validate_pipeline_url(
            "https://gitlab.example/team/project", PIPELINE_URL, 88), PIPELINE_URL)
        with self.assertRaises(status.StatusError):
            status.validate_pipeline_url(
                "https://gitlab.example/team/project", "https://evil.example/88", 88)

    def test_running_creates_one_status_note_and_terminal_state_updates_it(self):
        client = Mock()
        client.merge_request.return_value = merge_request()
        client.create_note.return_value = 91
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            self.assertEqual(
                status.publish(client, "running", 123, 7, SHA, 88, PIPELINE_URL, path),
                "running")
            self.assertTrue(path.exists())
            running_body = client.create_note.call_args.args[1]
            self.assertIn("리뷰 진행 중", running_body)
            self.assertIn("파이프라인 #88", running_body)

            client.reset_mock()
            client.merge_request.return_value = merge_request()
            self.assertEqual(
                status.publish(client, "success", 123, 7, SHA, 88, PIPELINE_URL, path),
                "success")
            completed_body = client.update_note.call_args.args[2]
            self.assertIn("리뷰 완료", completed_body)
            self.assertFalse(path.exists())

    def test_changed_head_updates_existing_note_as_canceled(self):
        client = Mock()
        client.merge_request.return_value = merge_request("b" * 40)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            status.write_private_status(path, {
                "iid": 7, "sha": SHA, "pipeline_id": 88, "note_id": 91,
            })
            self.assertEqual(
                status.publish(client, "failed", 123, 7, SHA, 88, PIPELINE_URL, path),
                "canceled")
            body = client.update_note.call_args.args[2]
            self.assertIn("리뷰 취소", body)
            self.assertIn("새 Push 또는 MR 상태 변경", body)

    def test_rejects_status_file_for_another_review(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            status.write_private_status(path, {
                "iid": 8, "sha": SHA, "pipeline_id": 88, "note_id": 91,
            })
            with self.assertRaises(status.StatusError) as raised:
                status.load_private_status(path, 7, SHA, 88)
            self.assertEqual(raised.exception.code, "STATUS_FILE_MISMATCH")

    def test_client_validates_mr_and_updates_only_selected_note(self):
        client = status.GitLabClient("https://gitlab.example/api/v4", 123, "secret", target_branch="develop")
        client.request = Mock(side_effect=[
            merge_request(), {"id": 91, "body": "running"},
            {"id": 91, "body": "finished"},
        ])
        self.assertEqual(client.merge_request(7)["sha"], SHA)
        self.assertEqual(client.create_note(7, "running"), 91)
        client.update_note(7, 91, "finished")
        self.assertEqual(client.request.call_args_list[1].args, (
            "POST", "/projects/123/merge_requests/7/notes", {"body": "running"}))
        self.assertEqual(client.request.call_args_list[2].args, (
            "PUT", "/projects/123/merge_requests/7/notes/91", {"body": "finished"}))

    def test_ci_updates_status_note_at_start_and_after_script(self):
        ci = (ROOT / "core" / "ci" / "gitlab" / "claude-review.yml").read_text(encoding="utf-8")
        section = ci[ci.index("harness-claude-review:"):]
        self.assertIn("review-status.py running", section)
        self.assertIn('review-status.py "$CI_JOB_STATUS"', section)
        self.assertIn('RUNNER_SCRIPT_TIMEOUT: "8m"', section)
        self.assertIn('RUNNER_AFTER_SCRIPT_TIMEOUT: "1m"', section)


if __name__ == "__main__":
    unittest.main()
