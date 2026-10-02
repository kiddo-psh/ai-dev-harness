"""Claude MR 리뷰 이관(M2-4)의 인수 테스트. 정책·서버 설정·자격 증명·신뢰 판정·init/check.

스크립트별 기존 동작은 test_claude_review_<스크립트>.py(feelm 테스트 이관)가 본다.
"""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "core" / "ci" / "claude-review"
FRAGMENT = ROOT / "core" / "ci" / "gitlab" / "claude-review.yml"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


harness_spec = importlib.util.spec_from_file_location("harness", ROOT / "bin" / "harness.py")
harness = importlib.util.module_from_spec(harness_spec)
harness_spec.loader.exec_module(harness)
common = load("review_common", "review_common.py")
collector = load("collect_mr", "collect-mr.py")
generator = load("generate_review", "generate-review.py")
publisher = load("publish_review", "publish-review.py")
status = load("review_status", "review-status.py")
auth = load("auth_check", "auth-check.py")
guard = load("network_guard", "network-guard.py")

# 스크립트마다 공통 모듈을 따로 읽으므로 예외 클래스도 모듈마다 다르다
ReviewErrors = tuple({m.common.ReviewError for m in (collector, generator, publisher, status, auth)}
                     | {common.ReviewError})
SHA = "a" * 40
BASE_CONFIG = {"project_name": "demo", "platform": "gitlab", "tracker": "jira", "issue_prefix": "DEMO",
               "default_branch": "main", "integration_branch": "develop"}
BLOCK = {"target_branch": "develop"}
POLICY = common.validate_policy(BLOCK)
TRUSTED_ENV = {"CI_COMMIT_BRANCH": "develop", "CI_COMMIT_REF_PROTECTED": "true",
               "CI_ENVIRONMENT_NAME": "claude-review", "CI_PIPELINE_SOURCE": "web",
               "GITLAB_REVIEW_TOKEN": "gitlab-secret", "ANTHROPIC_API_KEY": "api-secret",
               "CLAUDE_CODE_OAUTH_TOKEN": "oauth-secret", "CI_PROJECT_ID": "123",
               "REVIEW_MR_IID": "7", "REVIEW_MR_SHA": SHA, "CI_PIPELINE_ID": "88",
               "CI_PROJECT_URL": "https://gitlab.example/team/project",
               "CI_PIPELINE_URL": "https://gitlab.example/team/project/-/pipelines/88",
               "CI_API_V4_URL": "https://gitlab.example/api/v4"}
SERVER = {"claude_cli": "/opt/review/claude", "claude_version": "1.2.3", "workdir": "/tmp/review",
          "account": "review", "uid": 997, "home": "/home/review", "nft_table": "review_guard",
          "deny_ips": ["8.8.8.8"], "dns_ips": ["127.0.0.53"], "gitlab_host": "gitlab.example.com"}


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = harness.main(argv)
    return code, out.getvalue() + err.getvalue()


def main_of(module):
    return (lambda: module.main(["running"])) if module is status else module.main


@contextlib.contextmanager
def no_side_effects(module):
    """CLI 실행과 GitLab 호출을 가로채 호출되지 않았는지 확인한다."""
    with patch.object(module.common, "read_credential") as read_credential, \
            patch("subprocess.run") as run_cli, contextlib.ExitStack() as stack:
        client = (stack.enter_context(patch.object(module, "GitLabClient"))
                  if hasattr(module, "GitLabClient") else None)
        yield
        read_credential.assert_not_called()
        run_cli.assert_not_called()
        if client is not None:
            client.assert_not_called()


class PolicyValidationTest(unittest.TestCase):
    """T3: claude_review 미지 키, 잘못된 타입, 빈 대상 브랜치는 HarnessError, CLI는 종료 2."""

    BAD_BLOCKS = [
        None, [], "develop", {},
        {"target_branch": ""}, {"target_branch": "  "}, {"target_branch": 1},
        {"target_branch": "develop", "typo": True},
        {"target_branch": "develop", "credential": "password"},
        {"target_branch": "develop", "credential": None},
        {"target_branch": "develop", "environment": ""},
        {"target_branch": "develop", "review_name": "../etc"},
        {"target_branch": "develop", "review_name": "Review"},
        {"target_branch": "develop", "comment_marker": "a --> b"},
        {"target_branch": "develop", "rules_docs": []},
        {"target_branch": "develop", "rules_docs": ["AGENTS.md"]},
        {"target_branch": "develop", "rules_docs": [{"path": "../secret"}]},
        {"target_branch": "develop", "rules_docs": [{"path": "/etc/passwd"}]},
        {"target_branch": "develop", "rules_docs": [{"path": "a.md", "when": ["x/"]}]},
        {"target_branch": "develop", "rules_docs": [{"path": "a.md", "when_changed": []}]},
        {"target_branch": "develop", "rules_docs": [{"path": "a.md"}, {"path": "a.md"}]},
        {"target_branch": "develop", "limits": {"max_files": 0}},
        {"target_branch": "develop", "limits": {"max_files": True}},
        {"target_branch": "develop", "limits": {"max_files": "10"}},
        {"target_branch": "develop", "limits": {"max_files": 101}},  # 상한은 낮추기만 한다
        {"target_branch": "develop", "limits": {"max_lines": 10}},
        {"target_branch": "develop", "timeouts": {"claude_seconds": 301}},
        {"target_branch": "develop", "timeouts": []},
    ]

    def test_invalid_blocks_rejected(self):
        for block in self.BAD_BLOCKS:
            with self.subTest(block=block), self.assertRaises(harness.HarnessError):
                harness.validate_config({**BASE_CONFIG, "claude_review": block}, "test")

    def test_block_requires_gitlab(self):
        with self.assertRaises(harness.HarnessError):
            harness.validate_config({**BASE_CONFIG, "platform": "github", "tracker": "github",
                                     "claude_review": BLOCK}, "test")

    def test_defaults_and_valid_block(self):
        harness.validate_config({**BASE_CONFIG, "claude_review": BLOCK}, "test")
        self.assertEqual(POLICY["credential"], "api_key")  # D-29 기본값
        self.assertEqual(POLICY["environment"], "claude-review")
        self.assertEqual(POLICY["rules_docs"], [{"path": "AGENTS.md"}, {"path": "CLAUDE.md"}])
        self.assertEqual(POLICY["limits"], common.DEFAULT_LIMITS)
        full = {"target_branch": "release/next", "environment": "review", "review_name": "team-review",
                "credential": "oauth", "comment_marker": "team-review",
                "rules_docs": [{"path": "AGENTS.md"}, {"path": "docs/api.md", "when_changed": ["api/"]}],
                "limits": {"max_files": 50}, "timeouts": {"claude_seconds": 200}}
        policy = common.validate_policy(full)
        self.assertEqual(policy["limits"]["max_files"], 50)
        self.assertEqual(policy["timeouts"]["claude_seconds"], 200)

    def test_cli_exits_2(self):
        tmp = Path(tempfile.mkdtemp(prefix="harness-review-"))
        try:
            config = tmp / "harness.json"
            config.write_text(json.dumps({**BASE_CONFIG, "claude_review": {"target_branch": ""}}),
                              encoding="utf-8")
            code, out = run(["init", str(tmp / "target"), "--config", str(config)])
            self.assertEqual(code, 2)
            self.assertIn("target_branch", out)
            self.assertFalse((tmp / "target").exists())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_runtime_policy_load_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "harness.json"
            for content in ("not json", json.dumps(BASE_CONFIG),
                            json.dumps({**BASE_CONFIG, "claude_review": {"target_branch": ""}})):
                path.write_text(content, encoding="utf-8")
                with self.subTest(content=content[:20]), self.assertRaises(ReviewErrors) as raised:
                    common.load_policy(path)
                self.assertEqual(raised.exception.code, "INVALID_REVIEW_POLICY")
            path.write_text(json.dumps({**BASE_CONFIG, "claude_review": BLOCK}), encoding="utf-8")
            self.assertEqual(common.load_policy(path), POLICY)


class ServerConfigTest(unittest.TestCase):
    """T4: 서버 설정 파일 없음·필수 키 없음이면 리뷰 실행 전에 실패하고 토큰을 읽지 않는다."""

    def test_server_config_path_uses_review_name(self):
        policy = common.validate_policy({**BLOCK, "review_name": "team-review"})
        self.assertEqual(common.server_config_path(policy).as_posix(), "/etc/team-review/config.json")

    def test_validation(self):
        self.assertEqual(common.validate_server_config(dict(SERVER)), SERVER)
        bad = [dict(SERVER, extra=1), {k: v for k, v in SERVER.items() if k != "claude_cli"},
               dict(SERVER, claude_cli="claude"), dict(SERVER, workdir="/tmp/../etc"),
               dict(SERVER, uid=0), dict(SERVER, uid=True), dict(SERVER, account="Root User"),
               dict(SERVER, nft_table="bad-name"), dict(SERVER, gitlab_host="https://x"),
               dict(SERVER, claude_version="latest"), dict(SERVER, deny_ips="8.8.8.8")]
        for config in bad:
            with self.subTest(config=config), self.assertRaises(ReviewErrors) as raised:
                common.validate_server_config(config)
            self.assertEqual(raised.exception.code, "INVALID_SERVER_CONFIG")

    def test_missing_file_and_missing_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            with patch.object(common, "_require_root_owned"), self.assertRaises(ReviewErrors) as raised:
                common.load_server_config(path)
            self.assertEqual(raised.exception.code, "SERVER_CONFIG_UNAVAILABLE")
            path.write_text(json.dumps({k: v for k, v in SERVER.items() if k != "workdir"}), encoding="utf-8")
            with patch.object(common, "_require_root_owned"), self.assertRaises(ReviewErrors) as raised:
                common.load_server_config(path)
            self.assertEqual(raised.exception.code, "INVALID_SERVER_CONFIG")

    @unittest.skipIf(os.name == "nt", "소유자 검사는 Linux 서버에서만 한다")
    def test_non_root_config_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(SERVER), encoding="utf-8")
            with self.assertRaises(ReviewErrors) as raised:
                common.load_server_config(path)
            self.assertEqual(raised.exception.code, "UNSAFE_SERVER_CONFIG")

    def test_scripts_fail_before_reading_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "absent" / "config.json"
            for module, prefix in ((generator, "REVIEW_GENERATION"), (auth, "CLAUDE_AUTH_CHECK"),
                                   (collector, "MR_COLLECTION"), (publisher, "REVIEW_PUBLISH"),
                                   (status, "REVIEW_STATUS")):
                output = io.StringIO()
                with self.subTest(module=prefix), patch.dict(os.environ, TRUSTED_ENV, clear=True), \
                        patch.object(module.common, "load_policy", return_value=POLICY), \
                        patch.object(module.common, "server_config_path", return_value=missing), \
                        patch.object(module.common, "_require_root_owned"), \
                        no_side_effects(module), redirect_stdout(output):
                    self.assertEqual(main_of(module)(), 1)
                self.assertEqual(output.getvalue(), f"{prefix}: SERVER_CONFIG_UNAVAILABLE\n")


class CredentialTest(unittest.TestCase):
    """T5: credential이 고른 자격 증명 하나만 자식 환경에 들어간다."""

    def test_only_selected_credential_reaches_child(self):
        env = {"ANTHROPIC_API_KEY": "api-secret", "CLAUDE_CODE_OAUTH_TOKEN": "oauth-secret",
               "GITLAB_REVIEW_TOKEN": "gitlab-secret"}
        for credential, chosen, other, value in (("api_key", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "api-secret"),
                                                 ("oauth", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "oauth-secret")):
            with self.subTest(credential=credential):
                policy = common.validate_policy({**BLOCK, "credential": credential})
                name, token = common.read_credential(env, policy)
                self.assertEqual((name, token), (chosen, value))
                child = generator.child_environment(name, token, Path("/tmp/home"))
                self.assertEqual(child[chosen], value)
                self.assertNotIn(other, child)
                self.assertNotIn("GITLAB_REVIEW_TOKEN", child)
                self.assertNotIn("gitlab-secret", child.values())
                self.assertNotIn({"api_key": "oauth-secret", "oauth": "api-secret"}[credential], child.values())

    def test_selected_credential_missing_does_not_fall_back(self):
        policy = common.validate_policy(BLOCK)  # api_key
        with self.assertRaises(ReviewErrors) as raised:
            common.read_credential({"CLAUDE_CODE_OAUTH_TOKEN": "oauth-secret"}, policy)
        self.assertEqual(raised.exception.code, "MISSING_OR_INVALID_TOKEN")
        with self.assertRaises(ReviewErrors):
            common.read_credential({"ANTHROPIC_API_KEY": "with space"}, policy)
        with self.assertRaises(ReviewErrors):
            common.child_environment("GITLAB_REVIEW_TOKEN", "x", Path("/tmp/home"))

    def test_generate_main_passes_only_api_key(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "input.json"
            input_path.write_text(json.dumps({
                "untrusted_data": True,
                "merge_request": {"iid": 7, "target_branch": "develop", "sha": SHA},
                "files": [{"old_path": "a.py", "new_path": "a.py", "diff": "+x"}]}), encoding="utf-8")
            os.chmod(input_path, 0o600)
            server = dict(SERVER, workdir=directory)
            failure = subprocess.CompletedProcess([], 1, "other", "")
            with patch.dict(os.environ, TRUSTED_ENV, clear=True), \
                    patch.object(generator.common, "load_policy", return_value=POLICY), \
                    patch.object(generator.common, "load_server_config", return_value=server), \
                    patch.object(generator, "load_system_prompt", return_value="system"), \
                    patch.object(generator, "load_guidance", return_value="trusted"), \
                    patch.object(generator.subprocess, "run", return_value=failure) as run_cli, \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(generator.main(), 1)
            env = run_cli.call_args.kwargs["env"]
            self.assertEqual(env["ANTHROPIC_API_KEY"], "api-secret")
            self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", env)
            self.assertNotIn("GITLAB_REVIEW_TOKEN", env)
            self.assertEqual(run_cli.call_args.args[0][0], "/opt/review/claude")
            self.assertEqual(run_cli.call_args.kwargs["timeout"], 240)


class ToolFreeCommandTest(unittest.TestCase):
    """T6: CLI 인자 목록은 상수이며 고정 목록과 일치한다."""

    EXPECTED = ("-p", "--output-format", "json", "--max-turns", "1",
                "--tools", "", "--disable-slash-commands", "--setting-sources", "",
                "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--settings", '{"disableAllHooks":true}', "--no-session-persistence")

    def test_cli_args_pinned(self):
        self.assertEqual(common.CLI_ARGS, self.EXPECTED)
        self.assertEqual(generator.command("/opt/claude", "prompt"),
                         ["/opt/claude", *self.EXPECTED, "--system-prompt", "prompt"])
        self.assertEqual(auth.command("/opt/claude"), ["/opt/claude", *self.EXPECTED])


class TrustTest(unittest.TestCase):
    """T7: 설정값이 아닌 브랜치, MR 파이프라인, 보호되지 않은 ref면 리뷰를 생략하고 토큰을 쓰지 않는다."""

    UNTRUSTED = [{"CI_COMMIT_BRANCH": "main"}, {"CI_PIPELINE_SOURCE": "merge_request_event"},
                 {"CI_COMMIT_REF_PROTECTED": "false"}, {"CI_ENVIRONMENT_NAME": "production"},
                 {"CI_DEBUG_TRACE": "1"}, {"CI_DEBUG_SERVICES": "true"}, {"CI_PIPELINE_SOURCE": "schedule"},
                 {"CI_PIPELINE_SOURCE": "api"}]

    def test_policy_branch_is_used(self):
        policy = common.validate_policy({"target_branch": "main", "environment": "review"})
        env = dict(TRUSTED_ENV, CI_COMMIT_BRANCH="main", CI_ENVIRONMENT_NAME="review")
        self.assertTrue(common.trusted_context(env, policy))
        self.assertFalse(common.trusted_context(TRUSTED_ENV, policy))
        self.assertFalse(common.trusted_context(dict(env, CI_PIPELINE_SOURCE="api", CLAUDE_REVIEW_TRIGGER="comment"),
                                                policy, allow_api_trigger=False))

    def test_mr_pipeline_has_no_branch(self):
        env = {k: v for k, v in TRUSTED_ENV.items() if k != "CI_COMMIT_BRANCH"}
        env.update(CI_PIPELINE_SOURCE="merge_request_event", CI_MERGE_REQUEST_IID="7")
        self.assertFalse(common.trusted_context(env, POLICY))

    def test_scripts_skip_without_using_tokens(self):
        for module, prefix in ((generator, "REVIEW_GENERATION"), (auth, "CLAUDE_AUTH_CHECK"),
                               (collector, "MR_COLLECTION"), (publisher, "REVIEW_PUBLISH"),
                               (status, "REVIEW_STATUS")):
            for change in self.UNTRUSTED:
                output = io.StringIO()
                with self.subTest(module=prefix, change=change), \
                        patch.dict(os.environ, {**TRUSTED_ENV, **change}, clear=True), \
                        patch.object(module.common, "load_policy", return_value=POLICY), \
                        patch.object(module.common, "load_server_config") as server, \
                        no_side_effects(module), redirect_stdout(output):
                    self.assertEqual(main_of(module)(), 1)
                    server.assert_not_called()
                self.assertEqual(output.getvalue(), f"{prefix}: REJECTED_CI_CONTEXT\n")

    def test_mr_target_branch_must_match_policy(self):
        for check in (lambda: collector.validate_metadata(
                          {"iid": 7, "state": "opened", "target_branch": "main", "source_project_id": 1,
                           "target_project_id": 1, "sha": SHA}, 1, 7, SHA, "develop"),
                      lambda: publisher.validate_files(
                          {"untrusted_data": True, "merge_request": {"iid": 7, "target_branch": "main", "sha": SHA},
                           "files": []}, {"summary": "s", "findings": []}, 7, SHA, "develop")):
            with self.assertRaises(ReviewErrors):
                check()
        with self.assertRaises(ReviewErrors):  # 대상 브랜치를 모르면 통과시키지 않는다
            collector.validate_metadata({"iid": 7, "state": "opened", "target_branch": "", "source_project_id": 1,
                                         "target_project_id": 1, "sha": SHA}, 1, 7, SHA, "")


class PromptSourceTest(unittest.TestCase):
    """T8: CI 프롬프트는 M2-5 원본의 공통+CI 절에서 렌더한다."""

    def test_rendered_prompt_matches_source(self):
        config = {**BASE_CONFIG, "claude_review": BLOCK}
        outputs = harness.render_all(config, self_mode=False)
        ctx = harness.build_context(config)
        prompt = outputs[".harness/claude-review/system-prompt.md"]
        self.assertEqual(prompt, ctx["review_perspectives_ci"] + "\n")
        sections = harness.markdown_sections((harness.TEMPLATES_DIR / "review-perspectives.md").read_text(encoding="utf-8"))
        for name in ("공통", "CI"):
            first = next(line for line in sections[name].splitlines() if line.startswith("- "))
            self.assertIn(first.split("{{")[0], prompt)
        first_local = next(line for line in sections["로컬"].splitlines() if line.startswith("- "))
        self.assertNotIn(first_local.split("{{")[0], prompt)
        self.assertEqual(generator.SYSTEM_PROMPT_PATH.name, "system-prompt.md")

    def test_prompt_loader(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "system-prompt.md"
            with self.assertRaises(ReviewErrors):
                generator.load_system_prompt(path)
            path.write_text(" \n", encoding="utf-8")
            with self.assertRaises(ReviewErrors):
                generator.load_system_prompt(path)
            path.write_text("- 규칙\n", encoding="utf-8")
            self.assertEqual(generator.load_system_prompt(path), "- 규칙\n")


class LimitsTest(unittest.TestCase):
    """T9: 설정한 크기 상한으로 원본과 같은 거절 동작을 한다."""

    def change(self, size):
        return {"old_path": "a.py", "new_path": "a.py", "diff": "x" * size}

    def metadata(self):
        return {"iid": 7, "title": "t", "description": "d", "source_branch": "f", "target_branch": "develop",
                "sha": SHA}

    def test_configured_limits_reject(self):
        policy = common.validate_policy({**BLOCK, "limits": {"max_files": 1, "max_file_diff_bytes": 10,
                                                             "max_total_diff_bytes": 15,
                                                             "max_description_bytes": 1}})
        limits = policy["limits"]
        for changes, code in (([self.change(11)], "FILE_DIFF_LIMIT_EXCEEDED"),
                              ([self.change(10), self.change(10)], "TOTAL_DIFF_LIMIT_EXCEEDED")):
            with self.subTest(code=code), self.assertRaises(ReviewErrors) as raised:
                collector.build_review_input(self.metadata(), changes, limits)
            self.assertEqual(raised.exception.code, code)
        with self.assertRaises(ReviewErrors) as raised:
            collector.build_review_input(dict(self.metadata(), description="dd"), [self.change(1)], limits)
        self.assertEqual(raised.exception.code, "MR_METADATA_LIMIT_EXCEEDED")
        self.assertEqual(collector.build_review_input(self.metadata(), [self.change(10)], limits)["limits"],
                         {"file_count": 1, "total_diff_bytes": 10})

        class Response:
            def __init__(self, payload):
                self.body, self.headers = json.dumps(payload).encode(), {}

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self, limit):
                return self.body[:limit]

        meta = dict(self.metadata(), state="opened", source_project_id=1, target_project_id=1)
        responses = [Response(meta), Response({"changes": [self.change(1), self.change(1)]})]
        client = collector.GitLabClient("https://gitlab.example/api/v4", 1, "t", target_branch="develop",
                                        limits=limits, opener=lambda *_a, **_k: responses.pop(0))
        with self.assertRaises(ReviewErrors) as raised:
            client.collect(7, SHA)
        self.assertEqual(raised.exception.code, "DIFF_FILE_LIMIT_EXCEEDED")

    def test_context_and_guidance_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "AGENTS.md").write_text("x" * 20, encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("y" * 20, encoding="utf-8")
            payload = {"files": [{"old_path": "src/a.py", "new_path": "src/a.py", "diff": "+z"}]}
            with patch.object(generator, "ROOT", root):
                self.assertEqual(len(generator.load_repository_context(payload, {"max_context_file_bytes": 20})), 1)
                self.assertEqual(generator.load_repository_context(payload, {"max_context_file_bytes": 19}), [])
                self.assertEqual(generator.load_repository_context(payload, {"max_context_files": 1,
                                                                             "max_repository_context_bytes": 19}), [])
                policy = common.validate_policy({**BLOCK, "rules_docs": [{"path": "AGENTS.md"}],
                                                 "limits": {"max_guidance_bytes": 19}})
                with self.assertRaises(ReviewErrors) as raised:
                    generator.load_guidance(payload, policy)
                self.assertEqual(raised.exception.code, "TRUSTED_GUIDANCE_TOO_LARGE")


class MarkerTest(unittest.TestCase):
    """T10: 설정한 댓글 표식으로 같은 SHA의 기존 리뷰를 찾아 다시 게시하지 않는다."""

    def test_custom_marker_prevents_duplicate(self):
        marker = publisher.marker(123, 7, SHA, "team-review")
        self.assertEqual(marker, f"<!-- team-review:v1 project=123 mr=7 sha={SHA} -->")
        body = publisher.format_comment({"summary": "s", "findings": []}, 123, 7, SHA, 1, "team-review")
        self.assertTrue(body.startswith(marker))
        client = publisher.GitLabClient("https://gitlab.example/api/v4", 123, "t", target_branch="develop")
        notes = [{"body": publisher.marker(123, 7, SHA), "author": {"id": 55}},  # 기본 표식은 다른 표식이다
                 {"body": body, "author": {"id": 55}}]
        calls = []

        def request(method, path, payload=None, query=None):
            calls.append((method, path))
            if path.endswith("/notes") and method == "GET":
                return notes, {}
            if path == "/user":
                return {"id": 55}, {}
            return {"state": "opened", "target_branch": "develop", "source_project_id": 123,
                    "target_project_id": 123, "sha": SHA}, {}

        client.request = request
        self.assertEqual(publisher.publish(client, 7, SHA, body, "team-review"), "DUPLICATE_REVIEW_SKIPPED")
        self.assertNotIn("POST", [method for method, _ in calls])
        notes.pop()
        self.assertFalse(client.has_duplicate(7, marker, 55))

    def test_status_marker_uses_configured_name(self):
        self.assertIn("<!-- team-review-status:v1 project=1 mr=7", status.marker(1, 7, SHA, 88, "team-review"))
        body = status.format_comment("running", 1, 7, SHA, 88, "https://g.example/p/-/pipelines/88",
                                     marker_name="team-review")
        self.assertTrue(body.startswith("<!-- team-review-status:v1"))


class InitCheckTest(unittest.TestCase):
    """T11·T12: 블록이 있으면 init이 복사하고 check가 변조를 잡는다. 블록이 없으면 리뷰 파일이 없다."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="harness-review-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def init(self, config):
        path = self.tmp / "config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        target = self.tmp / "target"
        code, out = run(["init", str(target), "--config", str(path)])
        self.assertEqual(code, 0, out)
        return target

    def test_init_copies_and_check_detects_tamper(self):
        target = self.init({**BASE_CONFIG, "claude_review": BLOCK})
        review_dir = target / ".harness" / "claude-review"
        expected = {"system-prompt.md", "review_common.py", "collect-mr.py", "generate-review.py",
                    "publish-review.py", "review-status.py", "auth-check.py", "network-guard.py",
                    "sandbox-probe.py"}
        self.assertEqual({p.name for p in review_dir.iterdir()}, expected)
        for name in expected - {"system-prompt.md"}:
            self.assertEqual((review_dir / name).read_bytes().replace(b"\r\n", b"\n"),
                             (SCRIPTS / name).read_bytes().replace(b"\r\n", b"\n"), name)
        self.assertEqual(run(["check", str(target)])[0], 0)
        script = review_dir / "collect-mr.py"
        script.write_text(script.read_text(encoding="utf-8") + "\n# 변조\n", encoding="utf-8")
        code, out = run(["check", str(target)])
        self.assertEqual(code, 1)
        self.assertIn("불일치: .harness/claude-review/collect-mr.py", out)

    def test_prompt_source_change_is_drift(self):
        target = self.init({**BASE_CONFIG, "claude_review": BLOCK})
        original = harness.include_text
        with patch.object(harness, "include_text", lambda inc: original(inc) + "\n- 새 관점"):
            code, out = run(["check", str(target)])
        self.assertEqual(code, 1)
        self.assertIn("불일치: .harness/claude-review/system-prompt.md", out)

    def test_copied_scripts_run_from_target(self):
        target = self.init({**BASE_CONFIG, "claude_review": BLOCK})
        env = {key: value for key, value in os.environ.items() if not key.startswith("CI_")}
        result = subprocess.run([sys.executable, "-I", "-B", str(target / ".harness/claude-review/collect-mr.py")],
                                capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "MR_COLLECTION: REJECTED_CI_CONTEXT\n")  # 정책을 읽고 문맥에서 거부

    def test_without_block_nothing_changes(self):
        config = dict(BASE_CONFIG)
        outputs = harness.render_all(config, self_mode=False)
        self.assertFalse([dest for dest in outputs if dest.startswith(".harness/")])
        with_block = harness.render_all({**config, "claude_review": BLOCK}, self_mode=False)
        self.assertEqual({k: v for k, v in with_block.items() if not k.startswith(".harness/")}, outputs)
        target = self.init(config)
        self.assertFalse((target / ".harness").exists())
        self.assertEqual(run(["check", str(target)])[0], 0)
        self_outputs = harness.render_all(harness.load_config(ROOT / "harness.json"), self_mode=True)
        self.assertFalse([dest for dest in self_outputs if dest.startswith(".harness/")])  # D-34

    def test_manifest_requires_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            with patch.object(harness, "MANIFEST_PATH", manifest):
                for value in ("hooks", 1, None):
                    manifest.write_text(json.dumps({"files": [{"src": "AGENTS.md", "dest": "x", "requires": value}]}),
                                        encoding="utf-8")
                    with self.subTest(value=value), self.assertRaises(harness.HarnessError):
                        harness.load_manifest()


class ResidueTest(unittest.TestCase):
    """T2: 이관한 파일에 원본 프로젝트 고유값이 남지 않는다."""

    FORBIDDEN = re.compile(r"feelm|e106|ssafy|1441379|S15P21E106|j15e|-276\b|_276\b", re.IGNORECASE)
    # network-guard가 거부하는 특수 목적 대역의 시작 주소. 프로젝트 값이 아니다.
    RESERVED = {"0.0.0.0", "10.0.0.0", "100.64.0.0", "127.0.0.0", "169.254.0.0", "172.16.0.0",
                "192.168.0.0", "224.0.0.0", "240.0.0.0"}

    def files(self):
        paths = [p for p in SCRIPTS.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
        return paths + [FRAGMENT, harness.TEMPLATES_DIR / "claude-review" / "system-prompt.md"]

    def test_no_project_values(self):
        for path in self.files():
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertIsNone(self.FORBIDDEN.search(text))
                literals = set(re.findall(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?![\d.])", text))
                self.assertEqual(literals - self.RESERVED, set())


class ServerExampleTest(unittest.TestCase):
    def test_example_matches_contract_and_needs_input(self):
        example = json.loads((SCRIPTS / "examples" / "config.json.example").read_text(encoding="utf-8"))
        self.assertEqual(set(example), common.SERVER_KEYS)
        self.assertEqual(guard.SERVER_KEYS, common.SERVER_KEYS)
        self.assertEqual(example["deny_ips"], [])  # 운영 IP는 서버마다 다르다. 설치 시 필수 입력
        with self.assertRaises(ReviewErrors):
            common.validate_server_config(example)  # 채우기 전에는 쓸 수 없다
        with self.assertRaises(ValueError):
            guard.render(*guard.network_settings(example))

    def test_guard_reads_shared_config(self):
        network, table = guard.network_settings(SERVER)
        self.assertEqual(table, "review_guard")
        source = guard.render(network, table)
        self.assertIn("create table inet review_guard", source)
        self.assertIn("ip daddr 8.8.8.8 counter reject", source)  # 공개 주소 하나로도 동작한다
        for bad in (dict(SERVER, extra=1), dict(SERVER, nft_table="x; flush ruleset"), dict(SERVER, home="rel")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                guard.render(*guard.network_settings(bad))

    def test_units_point_to_shared_config(self):
        for name in ("guard", "probe", "runner"):
            text = (SCRIPTS / "examples" / f"claude-review-{name}.service.example").read_text(encoding="utf-8")
            for line in text.splitlines():
                if "network-guard.py" in line or "sandbox-probe.py" in line:
                    self.assertIn("--config /etc/claude-review/config.json", line)


class FragmentTest(unittest.TestCase):
    """GitLab 조각: 보호 대상 브랜치 파이프라인 전용(MR 파이프라인 없음), 원본 job 흐름 유지."""

    def test_rules_and_flow(self):
        text = FRAGMENT.read_text(encoding="utf-8")
        self.assertIn("<full-commit-sha>/core/ci/gitlab/claude-review.yml", text)
        self.assertNotIn("merge_request_event", text)
        body = text[text.index("\nharness-claude-auth-check:"):]
        rules = re.findall(r"- if: '(.+)'", body)
        self.assertEqual(len(rules), 3)
        for rule in rules:
            for needle in ('$CI_COMMIT_REF_PROTECTED == "true"', "$CI_COMMIT_BRANCH == $HARNESS_REVIEW_BRANCH",
                           "$HARNESS_REVIEW_RUNNER_TAG && $HARNESS_REVIEW_ENVIRONMENT"):
                self.assertIn(needle, rule)
        self.assertIn('$CI_PIPELINE_SOURCE == "push" || $CI_PIPELINE_SOURCE == "web"', rules[0])
        self.assertIn('$CI_PIPELINE_SOURCE == "api" && $CLAUDE_REVIEW_TRIGGER == "comment"', rules[1])
        self.assertTrue(rules[2].endswith('$CI_PIPELINE_SOURCE == "web"'))
        self.assertEqual(body.count("allow_failure: true"), 3)
        self.assertEqual(body.count("- $HARNESS_REVIEW_RUNNER_TAG"), 2)
        self.assertEqual(body.count("name: $HARNESS_REVIEW_ENVIRONMENT"), 2)
        scripts = re.findall(r"/usr/bin/python3 -I -B (\.harness/claude-review/[\w-]+\.py)", body)
        self.assertEqual([Path(s).name for s in scripts],
                         ["auth-check.py", "review-status.py", "collect-mr.py", "generate-review.py",
                          "publish-review.py", "review-status.py"])
        dests = {entry["dest"] for entry in harness.load_manifest()}
        for script in scripts:
            self.assertIn(script, dests)
        self.assertNotIn("CI_DEBUG_TRACE: ", body)


if __name__ == "__main__":
    unittest.main()
