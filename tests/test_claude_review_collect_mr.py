"""core/ci/claude-review/collect-mr.py (feelm test_collect_mr.py 이관)."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

SCRIPTS = Path(__file__).resolve().parent.parent / "core" / "ci" / "claude-review"
spec = importlib.util.spec_from_file_location("collect_mr", SCRIPTS / "collect-mr.py")
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)

SHA = "a" * 40
POLICY = collector.common.validate_policy({"target_branch": "develop"})


def client_for(opener):
    return collector.GitLabClient("https://gitlab.example/api/v4", 123, "secret", opener=opener,
                                  target_branch="develop")


def metadata(**changes):
    value = {
        "iid": 7,
        "state": "opened",
        "title": "example",
        "description": "description",
        "source_branch": "feat/example",
        "target_branch": "develop",
        "source_project_id": 123,
        "target_project_id": 123,
        "sha": SHA,
    }
    value.update(changes)
    return value


def diff(**changes):
    value = {
        "old_path": "before.py",
        "new_path": "after.py",
        "new_file": False,
        "renamed_file": True,
        "deleted_file": False,
        "generated_file": False,
        "diff": "@@ -1 +1 @@\n-old\n+new\n",
    }
    value.update(changes)
    return value


class Response:
    def __init__(self, payload, headers=None):
        self.body = json.dumps(payload).encode()
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, limit):
        return self.body[:limit]


@contextlib.contextmanager
def configured(workdir):
    with patch.object(collector.common, "load_policy", return_value=POLICY), \
            patch.object(collector.common, "load_server_config", return_value={"workdir": str(workdir), "gitlab_host": "gitlab.example"}):
        yield


class CollectorTests(unittest.TestCase):
    def test_collects_metadata_and_diff_without_executing_source(self):
        responses = [Response(metadata()), Response({"changes": [diff()]})]
        client = client_for(lambda *_args, **_kwargs: responses.pop(0))
        result = client.collect(7, SHA)
        self.assertTrue(result["untrusted_data"])
        self.assertEqual(result["merge_request"]["sha"], SHA)
        self.assertEqual(result["files"][0]["new_path"], "after.py")
        self.assertEqual(result["limits"]["file_count"], 1)

    def test_rejects_wrong_target_fork_and_changed_sha(self):
        cases = [
            (metadata(target_branch="main"), "TARGET_BRANCH_NOT_ALLOWED"),
            (metadata(source_project_id=456), "FORK_OR_DIFFERENT_PROJECT_REJECTED"),
            (metadata(sha="b" * 40), "MR_SHA_MISMATCH"),
        ]
        for value, code in cases:
            with self.subTest(code=code), self.assertRaises(collector.CollectionError) as raised:
                collector.validate_metadata(value, 123, 7, SHA, "develop")
            self.assertEqual(raised.exception.code, code)

    def test_rejects_incomplete_and_oversized_diffs(self):
        cases = [
            ([diff(collapsed=True)], "INCOMPLETE_DIFF_REJECTED"),
            ([diff(diff="x" * (collector.MAX_FILE_DIFF_BYTES + 1))], "FILE_DIFF_LIMIT_EXCEEDED"),
            ([diff(diff="x" * collector.MAX_FILE_DIFF_BYTES) for _ in range(5)],
             "TOTAL_DIFF_LIMIT_EXCEEDED"),
        ]
        for changes, code in cases:
            with self.subTest(code=code), self.assertRaises(collector.CollectionError) as raised:
                collector.build_review_input(metadata(), changes)
            self.assertEqual(raised.exception.code, code)

    def test_rejects_oversized_metadata(self):
        with self.assertRaises(collector.CollectionError) as raised:
            collector.build_review_input(metadata(description="가" * collector.MAX_DESCRIPTION_BYTES), [diff()])
        self.assertEqual(raised.exception.code, "MR_METADATA_LIMIT_EXCEEDED")

    # **이 인자가 빠지면 큰 파일이 있는 MR은 전부 리뷰를 못 받는다.**
    #
    # GitLab은 한 파일의 패치가 약 10KB를 넘으면 `collapsed`로 접어 빈 diff를 주고,
    # `build_review_input`이 그것을 `INCOMPLETE_DIFF_REJECTED`로 거절한다.
    # 접힌 파일을 펴는 경로는 `/changes?access_raw_diffs=true` 하나뿐이다(원본 운영에서 확인).
    def test_requests_raw_diffs_so_large_files_are_not_collapsed(self):
        requested = []

        def opener(request, **_kwargs):
            requested.append(request.full_url)
            return Response(metadata()) if len(requested) == 1 else Response({"changes": [diff()]})

        client = client_for(opener)
        client.collect(7, SHA)

        self.assertIn("/changes?", requested[1])
        self.assertIn("access_raw_diffs=true", requested[1])

    def test_rejects_changes_payload_that_is_not_a_list(self):
        responses = [Response(metadata()), Response({"changes": "not-a-list"})]
        client = client_for(lambda *_args, **_kwargs: responses.pop(0))
        with self.assertRaises(collector.CollectionError) as raised:
            client.collect(7, SHA)
        self.assertEqual(raised.exception.code, "INVALID_GITLAB_RESPONSE")

    def test_rejects_more_than_allowed_number_of_files(self):
        responses = [Response(metadata()),
                     Response({"changes": [diff()] * (collector.MAX_FILES + 1)})]
        client = client_for(lambda *_args, **_kwargs: responses.pop(0))
        with self.assertRaises(collector.CollectionError) as raised:
            client.collect(7, SHA)
        self.assertEqual(raised.exception.code, "DIFF_FILE_LIMIT_EXCEEDED")

    def test_maps_authentication_error_without_exposing_response(self):
        error = HTTPError("https://gitlab.example", 401, "secret", {}, None)
        client = client_for(lambda *_args, **_kwargs: (_ for _ in ()).throw(error))
        with self.assertRaises(collector.CollectionError) as raised:
            client.get("/example")
        self.assertEqual(raised.exception.code, "GITLAB_AUTHENTICATION_FAILED")

    def test_rejects_untrusted_pipeline_contexts(self):
        valid = {"CI_COMMIT_BRANCH": "develop", "CI_COMMIT_REF_PROTECTED": "true",
                 "CI_ENVIRONMENT_NAME": "claude-review", "CI_PIPELINE_SOURCE": "web"}
        for key, value in [("CI_COMMIT_BRANCH", "feat/example"),
                           ("CI_COMMIT_REF_PROTECTED", "false"),
                           ("CI_PIPELINE_SOURCE", "merge_request_event"),
                           ("CI_DEBUG_TRACE", "true")]:
            with self.subTest(key=key):
                self.assertFalse(collector.trusted_context(dict(valid, **{key: value}), POLICY))

    def test_accepts_only_tagged_api_trigger_context(self):
        valid = {"CI_COMMIT_BRANCH": "develop", "CI_COMMIT_REF_PROTECTED": "true",
                 "CI_ENVIRONMENT_NAME": "claude-review", "CI_PIPELINE_SOURCE": "api",
                 "CLAUDE_REVIEW_TRIGGER": "comment"}
        self.assertTrue(collector.trusted_context(valid, POLICY))
        self.assertFalse(collector.trusted_context(dict(valid, CLAUDE_REVIEW_TRIGGER="manual"), POLICY))

    def test_main_writes_private_file_and_does_not_print_token_or_diff(self):
        environment = {
            "CI_COMMIT_BRANCH": "develop", "CI_COMMIT_REF_PROTECTED": "true",
            "CI_ENVIRONMENT_NAME": "claude-review", "CI_PIPELINE_SOURCE": "web",
            "GITLAB_REVIEW_TOKEN": "synthetic-secret", "CI_PROJECT_ID": "123",
            "REVIEW_MR_IID": "7", "REVIEW_MR_SHA": SHA,
            "CI_API_V4_URL": "https://gitlab.example/api/v4",
        }
        payload = collector.build_review_input(metadata(), [diff(diff="private diff")])
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "review" / "input.json"
            output = io.StringIO()
            with patch.dict(os.environ, environment, clear=True), \
                    configured(output_path.parent), \
                    patch.object(collector.GitLabClient, "collect", return_value=payload), \
                    contextlib.redirect_stdout(output):
                self.assertEqual(collector.main(), 0)
            self.assertEqual(output.getvalue(), "MR_COLLECTION: PASS\n")
            self.assertNotIn("synthetic-secret", output.getvalue())
            self.assertNotIn("private diff", output.getvalue())
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8")), payload)
            if os.name != "nt":
                self.assertEqual(output_path.stat().st_mode & 0o777, 0o600)

    def test_main_removes_previous_input_before_failed_collection(self):
        environment = {
            "CI_COMMIT_BRANCH": "develop", "CI_COMMIT_REF_PROTECTED": "true",
            "CI_ENVIRONMENT_NAME": "claude-review", "CI_PIPELINE_SOURCE": "web",
            "GITLAB_REVIEW_TOKEN": "synthetic-secret", "CI_PROJECT_ID": "123",
            "REVIEW_MR_IID": "7", "REVIEW_MR_SHA": SHA,
            "CI_API_V4_URL": "https://gitlab.example/api/v4",
        }
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "input.json"
            output_path.write_text("stale", encoding="utf-8")
            with patch.dict(os.environ, environment, clear=True), \
                    configured(directory), \
                    patch.object(collector.GitLabClient, "collect",
                                 side_effect=collector.CollectionError("MR_SHA_MISMATCH")), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(collector.main(), 1)
            self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
