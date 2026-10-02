"""MR 본문 lint(M2-2, core/ci/mr-lint/mr_lint.py)와 GitLab 조각·키트 workflow job 구조."""

import importlib.util
import io
import json
import re
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("mr_lint", ROOT / "core" / "ci" / "mr-lint" / "mr_lint.py")
lint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lint)
HARNESS_SPEC = importlib.util.spec_from_file_location("harness_for_mr_lint", ROOT / "bin" / "harness.py")
harness = importlib.util.module_from_spec(HARNESS_SPEC)
HARNESS_SPEC.loader.exec_module(harness)
COMMON = ROOT / "core" / "hooks" / "harness_common.py"
FRAGMENT = ROOT / "core" / "ci" / "gitlab" / "mr-lint.yml"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

GITLAB_CONFIG = {"project_name": "demo", "platform": "gitlab", "tracker": "jira", "issue_prefix": "DEMO",
                 "default_branch": "main", "integration_branch": "develop"}


def template(platform="gitlab"):
    config = dict(GITLAB_CONFIG, platform=platform)
    ctx = harness.build_context(config)
    text = (harness.TEMPLATES_DIR / "merge-request" / "Default.md").read_text(encoding="utf-8")
    return harness.render(text, ctx)


def filled(tier="standard", strict_parts=False):
    """새 템플릿을 채운 본문. strict_parts면 플랜 요약·리뷰 결과와 측정 칸도 채운다."""
    body = template()
    body = body.replace("## 판정\n", "## 판정\n").replace(
        "-->\n\n-\n\n## 배경과 목적", f"-->\n\n- {tier} — 근거 한 줄\n\n## 배경과 목적")
    body = body.replace("- 방법:", "- 방법: unittest").replace("- 결과:", "- 결과: 통과").replace(
        "- 검증하지 못한 것과 남은 위험:", "- 검증하지 못한 것과 남은 위험: 없음")
    body = body.replace("- [ ] 해당 없음", "- [x] 해당 없음")
    if strict_parts:
        body = body.replace("-->\n\n해당 없음\n\n## 검토가 필요한 결정",
                            "-->\n\n- 설계 결정 두 개, 인수 테스트 T1~T5\n\n## 검토가 필요한 결정")
        body = body.replace("-->\n\n해당 없음\n\n| 항목", "-->\n\n- W2 리뷰 A·B, 발견 2건 모두 반영\n\n| 항목")
        for row, value in (("읽은 기준 문서 절 수 |", "6"), ("(동시성·트랜잭션 / 인가) |", "닫힘 / 열림"),
                           ("(참고 제외 / 참고) |", "2 / 1"), ("리뷰 세션 모델 |", "Claude Opus 5.5"),
                           ("(병합 후 기입) |", "병합 전")):
            body = body.replace(f"{row} |", f"{row} {value} |")
    return body


class BodyLintTest(unittest.TestCase):
    def test_valid_standard_body_passes(self):
        """T1"""
        result = lint.lint_body(filled(), "standard")
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["tier"], {"body": "standard", "judge": "standard", "effective": "standard",
                                          "mismatch": False})

    def test_rendered_template_fails_each_rule(self):
        """T2: 템플릿을 채우지 않으면 판정·검증 세 줄·영향 범위가 모두 실패한다(예시 Closes 줄은 남아 있다)."""
        for platform in ("gitlab", "github"):
            failures = " ".join(lint.lint_body(template(platform), None)["failures"])
            for needle in ("'방법' 값", "'결과' 값", "'미검증' 값", "`## 영향 범위`에 체크", "`## 판정` 값"):
                self.assertIn(needle, failures, platform)

    def test_closes_or_refs_required(self):
        """T3"""
        body = filled().replace("- Closes DEMO-52", "-")
        self.assertIn("`Closes` 또는 `Refs`", " ".join(lint.lint_body(body, None)["failures"]))
        hidden = filled().replace("- Closes DEMO-52", "<!-- Closes DEMO-52 -->")
        self.assertIn("`Closes` 또는 `Refs`", " ".join(lint.lint_body(hidden, None)["failures"]))
        empty = filled().replace("- Closes DEMO-52", "- Closes")
        self.assertIn("`Closes` 또는 `Refs`", " ".join(lint.lint_body(empty, None)["failures"]))
        refs = filled().replace("- Closes DEMO-52", "- refs DEMO-1")
        self.assertEqual(lint.lint_body(refs, None)["failures"], [])

    def test_verification_lines(self):
        """T4"""
        empty = filled().replace("- 방법: unittest", "- 방법:")
        self.assertEqual(lint.lint_body(empty, None)["failures"], ["`## 검증`의 '방법' 값이 비어 있다."])
        missing = filled().replace("- 결과: 통과\n", "")
        self.assertEqual(lint.lint_body(missing, None)["failures"], ["`## 검증`에 '결과' 줄이 없다."])
        nested = filled().replace("- 검증하지 못한 것과 남은 위험: 없음", "- 검증하지 못한 것과 남은 위험:\n  - GitLab 실환경")
        self.assertEqual(lint.lint_body(nested, None)["failures"], [])
        bold = filled().replace("- 방법: unittest", "- **방법**: unittest")
        self.assertEqual(lint.lint_body(bold, None)["failures"], [])
        no_section = filled().replace("## 검증", "## 확인")
        self.assertEqual(lint.lint_body(no_section, None)["failures"], ["`## 검증` 절이 없다."])

    def test_impact_needs_checked_box(self):
        """T5"""
        body = filled().replace("- [x] 해당 없음", "- [ ] 해당 없음")
        self.assertIn("체크한 항목이 없다", " ".join(lint.lint_body(body, None)["failures"]))
        upper = body.replace("- [ ] API 계약", "- [X] API 계약")
        self.assertEqual(lint.lint_body(upper, None)["failures"], [])

    def test_tier_values(self):
        """T6"""
        cases = {"standard": "standard", "표준 — 근거": "standard", "**엄격** 토큰 처리": "strict",
                 "STRICT": "strict", "lite(경량)": "lite", "경량": "lite"}
        for value, expected in cases.items():
            self.assertEqual(lint.parse_tier([f"- {value}"]), expected, value)
        for value in ("표준화", "medium", "", "판정: standard"):
            self.assertIsNone(lint.parse_tier([f"- {value}"]), value)
        body = filled().replace("## 판정", "## 단계")
        self.assertIn("`## 판정` 절이 없다.", lint.lint_body(body, None)["failures"])

    def test_strict_requires_plan_and_review(self):
        """T7"""
        na = lint.lint_body(filled("strict"), None)["failures"]
        self.assertIn("엄격 판정인데 `## 플랜 요약`가 '해당 없음'이다.", na)
        self.assertIn("엄격 판정인데 `## 리뷰 결과`가 '해당 없음'이다.", na)
        self.assertTrue(any("측정 칸 '읽은 기준 문서 절 수'이 비어" in f for f in na))
        ok = filled("strict", strict_parts=True)
        self.assertEqual(lint.lint_body(ok, None)["failures"], [])
        blank = ok.replace("| 리뷰 세션 모델 | Claude Opus 5.5 |", "| 리뷰 세션 모델 |  |")
        self.assertEqual(lint.lint_body(blank, None)["failures"], ["엄격 판정인데 `## 리뷰 결과` 측정 칸 '리뷰 세션 모델'이 비어 있다."])
        dropped = ok.replace("| 리뷰 세션 모델 | Claude Opus 5.5 |\n", "")
        self.assertEqual(lint.lint_body(dropped, None)["failures"],
                         ["엄격 판정인데 `## 리뷰 결과` 측정 칸에 '리뷰 세션 모델' 항목이 없다."])
        removed = re.sub(r"## 플랜 요약\n.*?(?=## 검토)", "", ok, flags=re.S)
        self.assertEqual(lint.lint_body(removed, None)["failures"], ["엄격 판정인데 `## 플랜 요약` 절이 없다."])
        # 측정 표가 아닌 내용에 "해당 없음"이 남아 있으면 요약과 함께 있어도 실패다
        both = ok.replace("- W2 리뷰 A·B", "해당 없음\n- W2 리뷰 A·B")
        self.assertIn("엄격 판정인데 `## 리뷰 결과`가 '해당 없음'이다.", lint.lint_body(both, None)["failures"])

    def test_judge_raises_tier_and_records_mismatch(self):
        """T8: 결정 D-10"""
        raised = lint.lint_body(filled("standard"), "strict")
        self.assertEqual(raised["tier"], {"body": "standard", "judge": "strict", "effective": "strict", "mismatch": True})
        self.assertIn("엄격 판정인데 `## 플랜 요약`가 '해당 없음'이다.", raised["failures"])
        higher = lint.lint_body(filled("strict", strict_parts=True), "lite")
        self.assertEqual(higher["tier"], {"body": "strict", "judge": "lite", "effective": "strict", "mismatch": True})
        self.assertEqual(higher["failures"], [])
        lower = lint.lint_body(filled("lite"), "standard")
        self.assertEqual((lower["tier"]["effective"], lower["tier"]["mismatch"], lower["failures"]), ("standard", True, []))
        unknown = lint.lint_body(filled("medium"), "strict")
        self.assertEqual(unknown["tier"]["effective"], "strict")
        self.assertFalse(unknown["tier"]["mismatch"])

    def test_code_block_heading_ignored(self):
        """T9"""
        body = "- Closes #1\n\n```\n## 판정\n- strict\n```\n"
        sections = lint.split_sections(lint.content_lines(body))
        self.assertNotIn("판정", sections)
        self.assertEqual(lint.split_sections(["## 판정", "~~~", "## 검증", "~~~", "- lite"])["판정"][-1], "- lite")

    def test_crlf_body(self):
        body = filled().replace("\n", "\r\n")
        self.assertEqual(lint.lint_body(body, "standard")["failures"], [])


class PlansRuleTest(unittest.TestCase):
    def test_plans_paths_and_gitignore(self):
        """T10: 결정 D-13"""
        ignore = "node_modules/\n/plans/\n"
        self.assertEqual(len(lint.plans_failures([("A", "plans/1.md")], ignore)), 1)
        self.assertEqual(len(lint.plans_failures([("M", "plans/1-review.md")], ignore)), 1)
        self.assertEqual(lint.plans_failures([("D", "plans/1.md")], ignore), [])
        self.assertEqual(lint.plans_failures([("A", "src/plans/x.py"), ("A", "plansx/a")], ignore), [])
        self.assertIn("`.gitignore`", lint.plans_failures([], None)[0])
        self.assertIn("`.gitignore`", lint.plans_failures([], "plans/\n/plans/x\n")[0])
        self.assertEqual(lint.plans_failures([], "  /plans/  \r\n"), [])


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    if args[0] != "commit":
        return None
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()


class RepoCase(unittest.TestCase):
    """harness.json·harness_common 사본·.gitignore가 있는 임시 git 저장소."""

    config = {"project_name": "demo", "platform": "gitlab", "tracker": "jira", "issue_prefix": "DEMO",
              "default_branch": "main", "integration_branch": "develop",
              "areas": [{"dir": "backend", "verify": ["true"], "trigger_paths": {"strict": ["/src/auth/"]}}]}

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="mr-lint-"))
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "t")
        git(self.repo, "config", "core.autocrlf", "false")
        (self.repo / ".claude" / "hooks").mkdir(parents=True)
        shutil.copy(COMMON, self.repo / ".claude" / "hooks" / "harness_common.py")
        (self.repo / "harness.json").write_text(json.dumps(self.config), encoding="utf-8")
        (self.repo / ".gitignore").write_text("/plans/\n", encoding="utf-8")
        (self.repo / "backend" / "src" / "auth").mkdir(parents=True)
        (self.repo / "backend" / "src" / "auth" / "a.py").write_text("a\n", encoding="utf-8")
        (self.repo / "old.txt").write_text("old\n", encoding="utf-8")
        (self.repo / "gone.txt").write_text("gone\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        self.base = git(self.repo, "commit", "-q", "-m", "base")
        git(self.repo, "switch", "-q", "-c", "feature")

    def commit(self, message="change"):
        git(self.repo, "add", "-A")
        return git(self.repo, "commit", "-q", "-m", message)


class GitChangesTest(RepoCase):
    def test_changes_and_judge_from_git(self):
        """T11"""
        (self.repo / "backend" / "src" / "auth" / "a.py").write_text("b\n", encoding="utf-8")
        (self.repo / "README.md").write_text("doc\n", encoding="utf-8")
        (self.repo / "gone.txt").unlink()
        (self.repo / "old.txt").rename(self.repo / "new.txt")
        head = self.commit()
        git(self.repo, "switch", "-q", "main")  # 대상 브랜치가 앞서가도 merge-base 이후만 본다
        (self.repo / "main-only.txt").write_text("x\n", encoding="utf-8")
        main_head = self.commit("main")
        changes = lint.changed(self.repo, main_head, head)
        self.assertEqual(sorted(changes), [("A", "README.md"), ("A", "new.txt"), ("D", "gone.txt"),
                                           ("D", "old.txt"), ("M", "backend/src/auth/a.py")])
        common = lint.load_common(self.repo / lint.DEFAULT_COMMON)
        self.assertFalse((self.repo / ".claude" / "hooks" / "__pycache__").exists())  # check의 여분 항목이 된다
        judged = lint.rejudge(self.repo, common, [p for _s, p in changes])
        self.assertEqual(judged, common.judge([p for _s, p in changes], self.config))
        self.assertEqual(judged["tier"], "strict")

    def test_errors(self):
        with self.assertRaises(lint.LintError):
            lint.changed(self.repo, "0" * 40, self.base)
        with self.assertRaises(lint.LintError):
            lint.changed(self.repo, "--output=x", self.base)
        with self.assertRaises(lint.LintError):
            lint.load_common(self.repo / "missing.py")
        (self.repo / "harness.json").write_text('{"judge": {"trigger_paths": {"bad": []}}}', encoding="utf-8")
        common = lint.load_common(self.repo / lint.DEFAULT_COMMON)
        with self.assertRaises(lint.LintError):
            lint.rejudge(self.repo, common, ["a"])


class ContextTest(unittest.TestCase):
    def test_gitlab_env(self):
        """T12"""
        env = {"GITLAB_CI": "true", "CI_MERGE_REQUEST_DESCRIPTION": "본문", "CI_MERGE_REQUEST_DIFF_BASE_SHA": "b",
               "CI_MERGE_REQUEST_SOURCE_BRANCH_SHA": "s", "CI_COMMIT_SHA": "m", "CI_API_V4_URL": "https://g/api/v4",
               "CI_PROJECT_ID": "7", "CI_MERGE_REQUEST_IID": "3"}
        ctx = lint.context_from_env(env)
        self.assertEqual((ctx["platform"], ctx["body"], ctx["base"], ctx["head"], ctx["number"]),
                         ("gitlab", "본문", "b", "s", "3"))
        self.assertEqual(lint.context_from_env({**env, "CI_MERGE_REQUEST_SOURCE_BRANCH_SHA": ""})["head"], "m")
        self.assertEqual(lint.context_from_env({**env, "CI_MERGE_REQUEST_DESCRIPTION": ""})["body"], "")
        missing = dict(env)
        del missing["CI_MERGE_REQUEST_DESCRIPTION"]
        with self.assertRaisesRegex(lint.LintError, "16.7"):
            lint.context_from_env(missing)
        with self.assertRaisesRegex(lint.LintError, "잘렸다"):
            lint.context_from_env({**env, "CI_MERGE_REQUEST_DESCRIPTION_IS_TRUNCATED": "true"})
        with self.assertRaises(lint.LintError):
            lint.context_from_env({})

    def test_github_event(self):
        """T13"""
        tmp = Path(tempfile.mkdtemp(prefix="mr-lint-event-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        event = tmp / "event.json"
        event.write_text(json.dumps({"pull_request": {"number": 9, "body": None, "base": {"sha": "b"},
                                                      "head": {"sha": "h"}}}), encoding="utf-8")
        env = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "pull_request", "GITHUB_EVENT_PATH": str(event),
               "GITHUB_API_URL": "https://api.github.com", "GITHUB_REPOSITORY": "o/r"}
        ctx = lint.context_from_env(env)
        self.assertEqual((ctx["platform"], ctx["body"], ctx["base"], ctx["head"], ctx["number"]),
                         ("github", "", "b", "h", "9"))
        with self.assertRaisesRegex(lint.LintError, "pull_request_target"):
            lint.context_from_env({**env, "GITHUB_EVENT_NAME": "pull_request_target"})
        event.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(lint.LintError, "pull_request가 없다"):
            lint.context_from_env(env)


class MainTest(RepoCase):
    def run_main(self, body, *extra, env=None):
        (self.repo / "body.md").write_text(body, encoding="utf-8")
        out_file = self.repo / "out.json"
        out = io.StringIO()
        with redirect_stdout(out):
            code = lint.main(["--project", str(self.repo), "--body-file", str(self.repo / "body.md"),
                              "--base", self.base, "--head", self.head, "--out", str(out_file), *extra],
                             env=env or {})
        return code, out.getvalue(), json.loads(out_file.read_text(encoding="utf-8"))

    def setUp(self):
        super().setUp()
        (self.repo / "src.py").write_text("x\n", encoding="utf-8")
        self.head = self.commit()

    def test_exit_codes_and_json(self):
        """T14"""
        code, out, report = self.run_main(filled())
        self.assertEqual(code, 0, out)
        self.assertEqual(report["result"], "pass")
        self.assertEqual(report["tier"]["effective"], "standard")
        self.assertEqual(report["comment"], "skipped")
        self.assertEqual([f["path"] for f in report["files"]], ["src.py"])
        self.assertIn("MR 본문 lint 통과", out)

        code, out, report = self.run_main(template())
        self.assertEqual(code, 1)
        self.assertEqual(report["result"], "fail")
        self.assertTrue(report["failures"])
        self.assertIn("MR 본문 lint 실패", out)

        (self.repo / "plans").mkdir()
        (self.repo / "plans" / "1.md").write_text("plan\n", encoding="utf-8")
        git(self.repo, "add", "-f", "plans/1.md")
        self.head = self.commit()
        code, _out, report = self.run_main(filled())
        self.assertEqual(code, 1)
        self.assertIn("플랜·리뷰 파일", report["failures"][0])

        (self.repo / lint.DEFAULT_COMMON).unlink()
        code, out, report = self.run_main(filled())
        self.assertEqual(code, 2)
        self.assertEqual(report["result"], "error")
        self.assertIn("검사할 수 없다", out)

    def test_judge_strict_requires_strict_sections(self):
        (self.repo / "backend" / "src" / "auth" / "a.py").write_text("c\n", encoding="utf-8")
        self.head = self.commit()
        code, _out, report = self.run_main(filled("standard"))
        self.assertEqual(code, 1)
        self.assertTrue(report["tier"]["mismatch"])
        code, _out, report = self.run_main(filled("strict", strict_parts=True))
        self.assertEqual(code, 0, report)

    def test_missing_gitignore_rule_fails(self):
        (self.repo / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
        code, _out, report = self.run_main(filled())
        self.assertEqual(code, 1)
        self.assertIn("`/plans/`", report["failures"][0])

    def test_comment_failure_keeps_exit_code(self):
        """T16: 댓글 실패는 lint 종료 코드를 바꾸지 않는다"""
        with mock.patch.object(lint, "try_comment", return_value="failed") as comment:
            code, _out, report = self.run_main(filled(), env={"HARNESS_COMMENT_TOKEN": "t"})
        self.assertEqual((code, report["comment"]), (0, "failed"))
        self.assertEqual(comment.call_args.args[2], "t")
        code, _out, report = self.run_main(filled(), "--no-comment", env={"HARNESS_COMMENT_TOKEN": "t"})
        self.assertEqual(report["comment"], "skipped")

    def test_local_run_needs_range(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = lint.main(["--project", str(self.repo), "--body-file", "x", "--out", str(self.repo / "o.json")],
                             env={})
        self.assertEqual(code, 2)


class FakeApi:
    """http_json 대역. (method, url, headers, data)를 기록하고 GET 응답은 표로 준다."""

    def __init__(self, pages=None, me=None, error=None):
        self.calls, self.pages, self.me, self.error = [], pages or [], me, error

    def __call__(self, method, url, headers, data=None):
        self.calls.append((method, url, headers, data))
        if self.error:
            raise self.error
        if method == "GET" and url.endswith("/user"):
            return {"id": self.me}
        if method == "GET":
            return self.pages
        return {"id": 1}


REPORT = {"result": "fail", "failures": ["`## 판정` 절이 없다."], "human_check": [{"area": None, "trigger": "x"}],
          "tier": {"body": None, "judge": "standard", "effective": "standard", "mismatch": False}}
GITLAB_CTX = {"platform": "gitlab", "api": "https://gitlab.example/api/v4", "project": "group/p", "number": "3"}
GITHUB_CTX = {"platform": "github", "api": "https://api.github.com", "project": "o/r", "number": "9"}


class CommentTest(unittest.TestCase):
    def comment(self, ctx, api, token="tok-secret"):
        out = io.StringIO()
        with mock.patch.object(lint, "http_json", api), redirect_stdout(out):
            status = lint.try_comment(ctx, REPORT, token)
        self.assertNotIn("tok-secret", out.getvalue())
        return status, out.getvalue()

    def test_creates_then_updates_marked_comment(self):
        """T15"""
        api = FakeApi(pages=[], me=5)
        self.assertEqual(self.comment(GITLAB_CTX, api)[0], "created")
        method, url, headers, data = api.calls[-1]
        self.assertEqual((method, url), ("POST", "https://gitlab.example/api/v4/projects/group%2Fp/merge_requests/3/notes"))
        self.assertEqual(headers["PRIVATE-TOKEN"], "tok-secret")
        self.assertTrue(data["body"].startswith(lint.MARKER))
        self.assertIn("`## 판정` 절이 없다.", data["body"])

        notes = [{"id": 11, "body": lint.MARKER + " old", "author": {"id": 6}},
                 {"id": 12, "body": lint.MARKER + " mine", "author": {"id": 5}}]
        api = FakeApi(pages=notes, me=5)
        self.assertEqual(self.comment(GITLAB_CTX, api)[0], "updated")
        self.assertEqual(api.calls[-1][:2], ("PUT", "https://gitlab.example/api/v4/projects/group%2Fp/merge_requests/3/notes/12"))
        api = FakeApi(pages=notes[:1], me=5)  # 남의 표식 댓글은 고치지 않는다
        self.assertEqual(self.comment(GITLAB_CTX, api)[0], "created")

        comments = [{"id": 21, "body": lint.MARKER, "user": {"login": "someone"}},
                    {"id": 22, "body": lint.MARKER, "user": {"login": "github-actions[bot]"}}]
        api = FakeApi(pages=comments)
        self.assertEqual(self.comment(GITHUB_CTX, api)[0], "updated")
        method, url, headers, _ = api.calls[-1]
        self.assertEqual((method, url), ("PATCH", "https://api.github.com/repos/o/r/issues/comments/22"))
        self.assertEqual(headers["Authorization"], "Bearer tok-secret")
        api = FakeApi(pages=comments[:1])
        self.assertEqual(self.comment(GITHUB_CTX, api)[0], "created")
        self.assertEqual(api.calls[-1][:2], ("POST", "https://api.github.com/repos/o/r/issues/9/comments"))

    def test_failure_is_warning_and_no_token_skips(self):
        """T16"""
        error = urllib.error.HTTPError("https://api.github.com/x", 403, "Forbidden", {}, None)
        status, out = self.comment(GITHUB_CTX, FakeApi(error=error))
        self.assertEqual(status, "failed")
        self.assertIn("HTTP 403", out)
        status, out = self.comment(GITHUB_CTX, FakeApi(error=urllib.error.URLError("down")))
        self.assertEqual(status, "failed")
        api = FakeApi()
        self.assertEqual(self.comment(GITHUB_CTX, api, token="")[0], "skipped")
        self.assertEqual(api.calls, [])
        status, _ = self.comment({**GITHUB_CTX, "api": "http://api.github.com"}, api)
        self.assertEqual((status, api.calls), ("failed", []))

    def test_comment_has_no_body_or_paths(self):
        text = lint.comment_text({**REPORT, "files": [{"path": "@everyone/x.py"}]})
        self.assertNotIn("@everyone", text)


class FragmentTest(unittest.TestCase):
    def test_structure(self):
        """T17: core/ci 조각 관례(test_ci.py)와 같은 형식"""
        text = FRAGMENT.read_text(encoding="utf-8")
        head = "\n".join(line for line in text.splitlines() if line.startswith("#"))
        for needle in ("include:", "- remote: https://", "core/ci/gitlab/mr-lint.yml", "필요 조건:", "예외:",
                       "HARNESS_COMMENT_TOKEN", "16.7", "2700자"):
            self.assertIn(needle, head)
        self.assertEqual(re.findall(r"^([^\s#][^:]*):\s*$", text, re.M), ["harness-mr-lint"])
        self.assertRegex(text, r"name: python:[\w.-]+@sha256:[0-9a-f]{64}\n")
        self.assertIn('  rules:\n    - if: $CI_PIPELINE_SOURCE == "merge_request_event"\n  interruptible', text)
        self.assertIn('GIT_DEPTH: "0"', text)
        self.assertNotIn("allow_failure", text)
        self.assertNotIn("set +e", text)
        self.assertRegex(text, r"script:\n    - \|\n      set -eu\n")
        for path in (".harness/mr-lint/mr_lint.py", ".claude/hooks/harness_common.py", "harness.json"):
            self.assertIn(path, text)
        self.assertIn("python3 -I -B .harness/mr-lint/mr_lint.py --out mr-lint.json", text)
        self.assertRegex(text, r"artifacts:\n    when: always\n    expire_in: 30 days\n    paths:\n      - mr-lint.json")

    def test_manifest_copies_module_for_gitlab(self):
        entries = [e for e in harness.load_manifest() if e["dest"] == ".harness/mr-lint/mr_lint.py"]
        self.assertEqual(entries, [{"base": "ci", "src": "mr-lint/mr_lint.py", "dest": ".harness/mr-lint/mr_lint.py",
                                    "self": False, "render": False, "platform": "gitlab"}])


class WorkflowTest(unittest.TestCase):
    def test_ci_mr_lint_job(self):
        """T18: 결정 D-11·D-12·D-14"""
        body = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("  pull_request:\n    types: [opened, synchronize, reopened, edited]\n", body)
        self.assertNotIn("pull_request_target", body.replace("pull_request_target은", ""))
        block = re.search(r"^  mr-lint:\n((?:(?:    .*)?\n)+)", body, re.M).group(1)
        lines = [line.split("  #")[0].rstrip() for line in block.splitlines()
                 if line.strip() and not line.lstrip().startswith("#")]
        self.assertEqual(lines, [
            "    if: github.event_name == 'pull_request'",
            "    runs-on: ubuntu-latest",
            "    timeout-minutes: 5",
            "    permissions:",
            "      contents: read",
            "      pull-requests: write",
            "    steps:",
            "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
            "        with:",
            "          fetch-depth: 0",
            "          persist-credentials: false",
            "      - name: PR 본문 lint",
            "        env:",
            "          HARNESS_COMMENT_TOKEN: ${{ github.token }}",
            "        run: python3 core/ci/mr-lint/mr_lint.py --out mr-lint.json",
            "      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
            "        if: always()",
            "        with:",
            "          name: mr-lint",
            "          path: mr-lint.json",
            "          retention-days: 30",
            "          if-no-files-found: ignore",
        ])


class TemplateTest(unittest.TestCase):
    def test_sections_and_measurement_rows(self):
        """T19: 결정 D-8. MR 템플릿 측정 칸 = 리뷰 템플릿 6장 = lint 상수"""
        mr = (harness.TEMPLATES_DIR / "merge-request" / "Default.md").read_text(encoding="utf-8")
        sections = harness.markdown_sections(mr)
        for title in ("판정", "플랜 요약", "리뷰 결과", "검증", "영향 범위", "관련 업무"):
            self.assertIn(title, sections)
        self.assertTrue(sections["플랜 요약"].rstrip().endswith(lint.NOT_APPLICABLE))
        review = harness.markdown_sections(
            (harness.TEMPLATES_DIR / "docs" / "templates" / "review.md").read_text(encoding="utf-8"))
        measure = next(body for title, body in review.items() if title.startswith("6."))
        mr_rows = [row[0] for row in lint.table_rows(sections["리뷰 결과"].splitlines())]
        review_rows = [row[0] for row in lint.table_rows(measure.splitlines())]
        self.assertEqual(mr_rows, review_rows)
        self.assertEqual(len(mr_rows), len(lint.MEASUREMENT_ROWS))
        for name, row in zip(lint.MEASUREMENT_ROWS, mr_rows):
            self.assertIn(name, row)

    def test_non_strict_template_defaults_are_not_failures(self):
        """비엄격 본문은 플랜 요약·리뷰 결과를 그대로 둬도 통과한다."""
        self.assertEqual(lint.lint_body(filled("lite"), "lite")["failures"], [])


if __name__ == "__main__":
    unittest.main()
