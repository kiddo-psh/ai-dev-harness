"""core/ci/claude-review/publish-review.py (feelm test_publish_review.py 이관)."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parent.parent / "core" / "ci" / "claude-review"
spec = importlib.util.spec_from_file_location("publish_review", SCRIPTS / "publish-review.py")
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)

SHA = "a" * 40
POLICY = publisher.common.validate_policy({"target_branch": "develop"})


def payload():
    return {"untrusted_data": True,
            "merge_request": {"iid": 7, "target_branch": "develop", "sha": SHA},
            "files": [{"new_path": "backend/example.py"}]}


def review(text="변경 로직을 확인했다.\n남은 검증 범위를 확인했다.", findings=None):
    return {"summary": text, "findings": findings or []}


def finding(**changes):
    value = {"severity": "HIGH", "file": "backend/example.py", "line": 10,
             "condition": "값이 비어 있을 때", "evidence": "검사가 없다.",
             "recommendation": "검사를 추가한다."}
    value.update(changes)
    return value


def write_private(path, text):
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o600)  # 게시기는 리뷰 계정만 읽을 수 있는 파일만 받는다(Linux)


class PublishReviewTests(unittest.TestCase):
    def test_accepts_only_tagged_api_trigger_context(self):
        valid = {"CI_COMMIT_BRANCH": "develop", "CI_COMMIT_REF_PROTECTED": "true",
                 "CI_ENVIRONMENT_NAME": "claude-review", "CI_PIPELINE_SOURCE": "api",
                 "CLAUDE_REVIEW_TRIGGER": "comment"}
        self.assertTrue(publisher.trusted_context(valid, POLICY))
        self.assertFalse(publisher.trusted_context(dict(valid, CLAUDE_REVIEW_TRIGGER="manual"), POLICY))

    def test_comment_has_stable_identifier_sha_and_ai_notice(self):
        body = publisher.format_comment(review(findings=[finding()]), 123, 7, SHA, 3)
        self.assertIn(publisher.marker(123, 7, SHA), body)
        self.assertIn("Claude 자동 코드 리뷰", body)
        self.assertIn(SHA, body)
        self.assertIn("⚠️ 문제 1건 발견", body)
        self.assertIn("**변경 파일:** 3개", body)
        self.assertIn("**심각도:** HIGH 1", body)
        self.assertIn("[HIGH · 병합 전 수정]", body)
        self.assertIn("**문제와 근거:**", body)
        self.assertIn("병합 판단 참고", body)
        self.assertIn("승인이나 병합을 의미하지 않습니다", body)

    def test_comment_without_findings_shows_success_first(self):
        body = publisher.format_comment(review(), 123, 7, SHA, 1)
        self.assertLess(body.index("✅ 발견된 문제 없음"), body.index("### 검토 결과"))
        self.assertNotIn("**심각도:**", body)
        self.assertIn("현재 변경에서 근거가 충분한 문제를 찾지 못했습니다.", body)

    def test_untrusted_markdown_is_confined_to_wrapping_inline_code(self):
        malicious = "@all\n/merge\n<script>alert(1)</script>\n```\noutside"
        body = publisher.format_comment(
            review(findings=[finding(condition=malicious)]), 123, 7, SHA, 1)
        self.assertIn("```` @all /merge <script>alert(1)</script> ``` outside 검사가 없다. ````", body)
        self.assertNotIn("\n/merge\n", body)

    def test_duplicate_from_same_bot_skips_post(self):
        client = Mock(project_id=123)
        client.current_sha.return_value = SHA
        client.current_user_id.return_value = 55
        client.has_duplicate.return_value = True
        self.assertEqual(publisher.publish(client, 7, SHA, "body"), "DUPLICATE_REVIEW_SKIPPED")
        client.create_note.assert_not_called()

    def test_matching_marker_from_other_author_is_not_duplicate(self):
        marker = publisher.marker(123, 7, SHA)
        responses = [([{"body": marker, "author": {"id": 99}}], {})]
        client = publisher.GitLabClient("https://gitlab.example/api/v4", 123, "token", target_branch="develop")
        client.request = Mock(side_effect=responses)
        self.assertFalse(client.has_duplicate(7, marker, 55))

    def test_stale_before_post_never_creates_note(self):
        client = Mock(project_id=123)
        client.current_sha.return_value = "b" * 40
        with self.assertRaises(publisher.PublishError) as raised:
            publisher.publish(client, 7, SHA, "body")
        self.assertEqual(raised.exception.code, "STALE_REVIEW_REJECTED")
        client.create_note.assert_not_called()

    def test_stale_after_post_removes_only_new_note(self):
        client = Mock(project_id=123)
        client.current_sha.side_effect = [SHA, SHA, "b" * 40]
        client.current_user_id.return_value = 55
        client.has_duplicate.return_value = False
        client.create_note.return_value = 91
        with self.assertRaises(publisher.PublishError) as raised:
            publisher.publish(client, 7, SHA, "body")
        self.assertEqual(raised.exception.code, "STALE_REVIEW_REMOVED")
        client.delete_note.assert_called_once_with(7, 91)

    def test_success_checks_sha_before_and_after_post(self):
        client = Mock(project_id=123)
        client.current_sha.side_effect = [SHA, SHA, SHA]
        client.current_user_id.return_value = 55
        client.has_duplicate.return_value = False
        client.create_note.return_value = 91
        self.assertEqual(publisher.publish(client, 7, SHA, "body"), "PASS")
        self.assertEqual(client.current_sha.call_count, 3)

    def test_rejects_review_for_different_sha_or_file(self):
        for current_payload, current_review in [
                (dict(payload(), merge_request={"iid": 7, "target_branch": "develop", "sha": "b" * 40}), review()),
                (payload(), review(findings=[finding(file="other.py")]))]:
            with self.subTest(current_review=current_review), self.assertRaises(publisher.PublishError):
                publisher.validate_files(current_payload, current_review, 7, SHA, "develop")

    def test_merge_guidance_groups_findings_by_required_action(self):
        findings = [finding(severity="BLOCKER"), finding(severity="HIGH"),
                    finding(severity="MEDIUM"), finding(severity="LOW")]
        body = publisher.format_comment(review(findings=findings), 123, 7, SHA, 1)
        self.assertIn("**병합 전 수정:** 2건", body)
        self.assertIn("**병합 전 확인:** 1건", body)
        self.assertIn("**후속 작업 후보:** 1건", body)
        self.assertIn("병합 전 수정 권장 항목이 있습니다", body)

    def test_main_never_prints_comment_or_token(self):
        environment = {"CI_COMMIT_BRANCH": "develop", "CI_COMMIT_REF_PROTECTED": "true",
                       "CI_ENVIRONMENT_NAME": "claude-review", "CI_PIPELINE_SOURCE": "web",
                       "GITLAB_REVIEW_TOKEN": "synthetic-secret", "CI_PROJECT_ID": "123",
                       "REVIEW_MR_IID": "7", "REVIEW_MR_SHA": SHA,
                       "CI_API_V4_URL": "https://gitlab.example/api/v4"}
        with tempfile.TemporaryDirectory() as directory:
            input_path, review_path = Path(directory) / "input.json", Path(directory) / "review.json"
            write_private(input_path, json.dumps(payload()))
            write_private(review_path, json.dumps(review("private review\nprivate limitation")))
            output = io.StringIO()
            with patch.dict(os.environ, environment, clear=True), \
                    patch.object(publisher.common, "load_policy", return_value=POLICY), \
                    patch.object(publisher.common, "load_server_config", return_value={"workdir": directory, "gitlab_host": "gitlab.example"}), \
                    patch.object(publisher, "publish", return_value="PASS"), \
                    contextlib.redirect_stdout(output):
                self.assertEqual(publisher.main(), 0)
            self.assertEqual(output.getvalue(), "REVIEW_PUBLISH: PASS\n")
            self.assertNotIn("synthetic-secret", output.getvalue())
            self.assertNotIn("private review", output.getvalue())


if __name__ == "__main__":
    unittest.main()
