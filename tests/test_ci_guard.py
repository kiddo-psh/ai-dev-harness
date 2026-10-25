"""#100 M5-5 hooks가 없는 도구를 위한 CI 측 보호: MR lint 보호 경로 확인과 변경 영역 검증."""

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tempdirs import remove_tree  # noqa: E402
from test_mr_lint import RepoCase, filled, git, lint  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("verify_changed", ROOT / "core" / "ci" / "verify" / "verify_changed.py")
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)
CONFIRMED = "- [x] 보호 경로 변경을 사람이 확인했다"


class ProtectedLintTest(RepoCase):
    def lint(self, body, head):
        (self.repo / "body.md").write_text(body, encoding="utf-8")
        out = self.repo / "out.json"
        with redirect_stdout(io.StringIO()) as stdout:
            code = lint.main(["--project", str(self.repo), "--body-file", str(self.repo / "body.md"),
                              "--base", self.base, "--head", head, "--out", str(out), "--no-comment"], env={})
        return code, json.loads(out.read_text(encoding="utf-8")), stdout.getvalue()

    def protected_failures(self, report):
        return [f for f in report["failures"] if f.startswith("보호 경로를 바꿨다")]

    def test_lock_file_without_confirmation_fails(self):
        """T1"""
        (self.repo / "backend" / "package-lock.json").write_text("{}", encoding="utf-8")
        code, report, _ = self.lint(filled(), self.commit())
        self.assertEqual(code, 1)
        [failure] = self.protected_failures(report)
        self.assertIn("`backend/package-lock.json`(lock 파일", failure)

    def test_migration_with_checked_confirmation_passes(self):
        """T2"""
        (self.repo / "backend" / "src" / "main" / "resources" / "db" / "migration").mkdir(parents=True)
        (self.repo / "backend" / "src" / "main" / "resources" / "db" / "migration" / "V1__a.sql").write_text(
            "create table a(id int);\n", encoding="utf-8")
        head = self.commit()
        body = filled().replace("- [ ] 보호 경로 변경을 사람이 확인했다", CONFIRMED)
        code, report, out = self.lint(body, head)
        self.assertEqual(self.protected_failures(report), [], out)
        self.assertEqual(code, 0, report["failures"])
        _, report, _ = self.lint(filled(), head)
        self.assertIn("DB 마이그레이션", self.protected_failures(report)[0])

    def test_unchecked_or_commented_confirmation_fails(self):
        """T3"""
        (self.repo / ".gitlab-ci.yml").write_text("x: 1\n", encoding="utf-8")
        head = self.commit()
        commented = filled().replace("- [ ] 보호 경로 변경을 사람이 확인했다", f"<!-- {CONFIRMED} -->")
        for body in (filled(), commented, filled().replace("## 보호 경로 확인", "## 확인 없음")):
            with self.subTest(body=body[-200:]):
                self.assertEqual(len(self.protected_failures(self.lint(body, head)[1])), 1)

    def test_rules_from_base_config(self):
        """T4: MR이 같은 MR에서 protected_paths를 비워도 대상 쪽 규칙으로 검사한다"""
        config = json.loads((self.repo / "harness.json").read_text(encoding="utf-8"))
        config["hooks"] = {"protected_paths": []}
        (self.repo / "harness.json").write_text(json.dumps(config), encoding="utf-8")
        (self.repo / "yarn.lock").write_text("x\n", encoding="utf-8")
        _, report, _ = self.lint(filled(), self.commit())
        paths = self.protected_failures(report)[0]
        self.assertIn("`yarn.lock`", paths)
        self.assertIn("`harness.json`", paths)  # 끌 수 없는 규칙

    def test_delete_rename_and_kit_code(self):
        """리뷰 A F5·F1: 보호 경로 삭제·이름 변경과 `.harness/`(CI 검사 코드) 변경도 확인을 요구한다"""
        (self.repo / "old.txt").rename(self.repo / "package-lock.json")  # 이름 변경으로 보호 경로를 만든다
        (self.repo / ".harness" / "mr-lint").mkdir(parents=True)
        (self.repo / ".harness" / "mr-lint" / "mr_lint.py").write_text("# 무력화\n", encoding="utf-8")
        failure = self.protected_failures(self.lint(filled(), self.commit())[1])[0]
        self.assertIn("`package-lock.json`", failure)
        self.assertIn("`.harness/mr-lint/mr_lint.py`(키트 CI 검사 코드)", failure)
        git(self.repo, "switch", "-q", "main")  # 기준에 보호 경로를 두고 MR에서 지운다
        (self.repo / "yarn.lock").write_text("x\n", encoding="utf-8")
        self.base = self.commit("lock")
        git(self.repo, "switch", "-q", "-c", "delete-lock")
        git(self.repo, "rm", "-q", "yarn.lock")
        self.assertIn("`yarn.lock`", self.protected_failures(self.lint(filled(), self.commit())[1])[0])

    def test_checkbox_in_code_block_does_not_count(self):
        (self.repo / "yarn.lock").write_text("x\n", encoding="utf-8")
        head = self.commit()
        body = filled().replace("- [ ] 보호 경로 변경을 사람이 확인했다", "```\n" + CONFIRMED + "\n```")
        self.assertEqual(len(self.protected_failures(self.lint(body, head)[1])), 1)

    def test_malformed_base_config_falls_back_to_defaults(self):
        """리뷰 B F1·A F2: 기준 커밋 설정이 잘못돼도 traceback 없이 기본 보호 경로로 검사한다"""
        git(self.repo, "switch", "-q", "main")
        config = json.loads((self.repo / "harness.json").read_text(encoding="utf-8"))
        config["hooks"] = {"protected_paths": [{"pattern": "x", "mode": "warn"}]}
        (self.repo / "harness.json").write_text(json.dumps(config), encoding="utf-8")
        self.base = self.commit("bad rules")
        git(self.repo, "switch", "-q", "-c", "fix-rules")
        (self.repo / "pnpm-lock.yaml").write_text("x\n", encoding="utf-8")
        code, report, out = self.lint(filled(), self.commit())
        self.assertIn("기준 설정이 잘못돼 기본 보호 경로로 검사한다", out)
        self.assertIn("`pnpm-lock.yaml`", self.protected_failures(report)[0])
        self.assertEqual(code, 1)

    def test_base_without_config_uses_mr_config(self):
        git(self.repo, "switch", "-q", "main")
        git(self.repo, "rm", "-q", "harness.json")
        self.base = self.commit("no config")
        git(self.repo, "switch", "-q", "-c", "add-config")
        (self.repo / "harness.json").write_text(json.dumps(self.config), encoding="utf-8")
        failure = self.protected_failures(self.lint(filled(), self.commit())[1])[0]
        self.assertIn("`harness.json`", failure)  # 설정 추가 자체가 끌 수 없는 규칙에 걸린다

    def test_no_protected_paths_unaffected(self):
        """T5"""
        (self.repo / "src.py").write_text("x\n", encoding="utf-8")
        code, report, _ = self.lint(filled(), self.commit())
        self.assertEqual((code, report["failures"]), (0, []))

    def test_rule_change_follows_hooks(self):
        """T6: 대상 쪽 설정 규칙을 바꾸면 lint 결과도 같이 바뀐다(hook과 같은 함수)"""
        git(self.repo, "switch", "-q", "main")
        config = json.loads((self.repo / "harness.json").read_text(encoding="utf-8"))
        config["hooks"] = {"protected_paths": [{"pattern": "docs/api/**", "mode": "ask", "reason": "API 계약"}]}
        (self.repo / "harness.json").write_text(json.dumps(config), encoding="utf-8")
        self.base = self.commit("rules")
        git(self.repo, "switch", "-q", "-c", "feature2")
        (self.repo / "docs" / "api").mkdir(parents=True)
        (self.repo / "docs" / "api" / "x.md").write_text("x\n", encoding="utf-8")
        (self.repo / "package-lock.json").write_text("{}", encoding="utf-8")  # 기본 목록을 대체했으므로 보호 아님
        _, report, _ = self.lint(filled(), self.commit())
        [failure] = self.protected_failures(report)
        self.assertIn("`docs/api/x.md`(API 계약)", failure)
        self.assertNotIn("package-lock.json", failure)


class VerifyChangedTest(RepoCase):
    def run_verify(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = verify.run(["--project", str(self.repo), *args])
        return code, out.getvalue(), err.getvalue()

    def set_config(self, **changes):
        config = json.loads((self.repo / "harness.json").read_text(encoding="utf-8"))
        config.update(changes)
        (self.repo / "harness.json").write_text(json.dumps(config), encoding="utf-8")

    def test_runs_changed_area_commands_only(self):
        """T8"""
        py = Path(sys.executable).as_posix()
        self.set_config(areas=[{"dir": "backend", "verify": [f'"{py}" -c "print(\'backend-ok\')"']},
                               {"dir": "web", "verify": [f'"{py}" -c "raise SystemExit(3)"']}],
                        hooks={"stop_verify": [f'"{py}" -c "print(\'root-ok\')"']})
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "config")
        (self.repo / "backend" / "src" / "auth" / "a.py").write_text("b\n", encoding="utf-8")
        self.commit()
        code, out, err = self.run_verify("--base", self.base)
        self.assertEqual(code, 0, err)
        self.assertIn("실행할 검증 명령 2개", out)  # backend 영역 + harness.json(영역 밖)
        (self.repo / "web").mkdir()
        (self.repo / "web" / "a.ts").write_text("x\n", encoding="utf-8")
        self.commit()
        code, _, err = self.run_verify("--base", self.base)
        self.assertEqual(code, 1)
        self.assertIn("실패", err)

    def test_bash_syntax_command(self):
        """#115: CI 검증도 종료 검증과 같은 셸(Windows는 Git Bash)에서 bash 문법 명령을 실행한다"""
        self.set_config(hooks={"stop_verify": ["test -d . && cd backend && test \"$(printf %s 'a\\\\b' | wc -c)\" -eq 4"]})
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "config")
        (self.repo / "top.txt").write_text("x\n", encoding="utf-8")
        self.commit()
        code, out, err = self.run_verify("--base", self.base)
        self.assertEqual(code, 0, out + err)

    def test_no_changes_and_errors(self):
        code, out, _ = self.run_verify("--base", "HEAD")
        self.assertEqual(code, 0)
        self.assertIn("실행할 검증 명령 0개", out)
        self.assertEqual(self.run_verify("--base", "origin/nope")[0], 2)
        self.assertEqual(self.run_verify("--base=--evil")[0], 2)  # git 옵션으로 해석되지 않게 거절

    def write_conflicting_node(self):
        (self.repo / ".nvmrc").write_text("22\n", encoding="utf-8")
        (self.repo / ".gitlab-ci.yml").write_text("test:\n  image: node:20.19-alpine\n", encoding="utf-8")

    def test_parity_failure_blocks_before_commands(self):
        """#152 T8: Node 선언이 어긋나면 영역 명령을 실행하지 않고 실패한다. HARNESS_VERIFY_PARITY=off면 건너뛴다"""
        marker = (self.repo / "ran.txt").as_posix()
        py = Path(sys.executable).as_posix()
        self.set_config(areas=[{"dir": "backend", "verify": [f'"{py}" -c "open(\'{marker}\', \'w\').close()"']}])
        self.write_conflicting_node()
        (self.repo / "backend" / "src" / "auth" / "a.py").write_text("b\n", encoding="utf-8")
        self.commit()
        with patch.dict(os.environ, {"HARNESS_VERIFY_PARITY": ""}):
            code, _, err = self.run_verify("--base", self.base)
        self.assertEqual(code, 1, err)
        self.assertIn("고정 버전이 서로 다르다", err)
        self.assertIn("HARNESS_VERIFY_PARITY=off", err)
        self.assertFalse(Path(marker).exists())
        with patch.dict(os.environ, {"HARNESS_VERIFY_PARITY": "off"}):
            code, _, err = self.run_verify("--base", self.base)
        self.assertEqual(code, 0, err)
        self.assertTrue(Path(marker).exists())

    def test_no_commands_skips_parity(self):
        """#152 T9: 실행할 명령이 없으면 런타임이 결과에 영향을 주지 않으므로 검사하지 않는다"""
        self.write_conflicting_node()
        self.commit()
        with patch.dict(os.environ, {"HARNESS_VERIFY_PARITY": ""}):
            code, out, err = self.run_verify("--base", "HEAD")
        self.assertEqual(code, 0, err)
        self.assertIn("실행할 검증 명령 0개", out)


class NodeParityTest(unittest.TestCase):
    """#152: 로컬·CI Node 버전 선언 패리티. 실행 중인 node는 runtime 인자로 고정한다."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="harness-parity-"))
        self.addCleanup(remove_tree, self.repo)

    def write(self, rel, text):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def parity(self, runtime=None, areas=()):
        return verify.node_parity(self.repo, {"areas": [{"dir": d} for d in areas]}, runtime=runtime)

    def test_feelm_case(self):
        """T1: engines `>=20.19.0`은 CI·Docker의 20.19를 만족하지만 로컬 22도 통과시킨다"""
        self.write("package.json", json.dumps({"engines": {"node": ">=20.19.0"}}))
        self.write("Dockerfile", "FROM node:20.19-alpine AS build\nFROM nginx:1.27\n")
        self.write(".gitlab-ci.yml", "frontend-test:\n  image: node:20.19-alpine\n")
        problems, _ = self.parity()
        [problem] = problems
        self.assertIn("package.json의 engines.node `>=20.19.0`가 고정 버전의 메이저(20) 밖의 Node 21, 22, 23 등도 허용한다", problem)
        self.assertIn("<21", problem)
        problems, _ = self.parity(runtime=(22, 11, 0))  # 그 상태에서 로컬 22로 돌리면 실행 중 node 불일치도 나온다
        self.assertTrue(any(p.startswith("실행 중인 node 22.11.0가 고정 버전과 다르다") for p in problems), problems)

    def test_pins_conflict(self):
        """T2"""
        self.write(".nvmrc", "v22.22.0\n")
        self.write(".gitlab-ci.yml", "variables:\n  HARNESS_VERIFY_IMAGE: \"node:20.19\"\n# image: node:18\n")
        [problem], _ = self.parity()
        self.assertEqual(problem, "고정 버전이 서로 다르다: .nvmrc 22.22.0, .gitlab-ci.yml:2 20.19")

    def test_consistent_passes(self):
        """T3"""
        self.write("package.json", json.dumps({"engines": {"node": "^22.22.0"}}))
        self.write(".nvmrc", "22\n")
        self.write("Dockerfile.prod", "FROM --platform=linux/amd64 docker.io/library/node:22.22.0-alpine\n")
        self.write(".gitlab-ci.yml", "image:\n  name: node:22.22-bookworm\n")
        self.assertEqual(self.parity(runtime=(22, 22, 1)), ([], []))

    def test_runtime_mismatch(self):
        """T4"""
        self.write(".node-version", "22\n")
        self.write("package.json", json.dumps({"engines": {"node": ">=22 <23"}}))
        problems, _ = self.parity(runtime=(20, 19, 0))
        self.assertEqual(problems, ["실행 중인 node 20.19.0가 고정 버전과 다르다: .node-version 22",
                                    "실행 중인 node 20.19.0가 package.json의 engines.node `>=22 <23` 밖이다"])

    def test_ignores_non_numeric_and_missing(self):
        """T5: 숫자가 아닌 선언과 깨진 파일은 실패로 만들지 않는다. 선언이 없으면 node를 실행하지 않는다"""
        self.write(".nvmrc", "lts/*\n")
        self.write("Dockerfile", "ARG V=22\nFROM node:${V}\nFROM node:lts-alpine\nFROM mynode:18\n")
        self.write(".gitlab-ci.yml", "image: node:lts\nimage: registry/mynode:18\n")
        with patch.object(verify, "detect_node", side_effect=AssertionError("node를 실행하면 안 된다")):
            self.assertEqual(self.parity(runtime=verify._DETECT), ([], []))
        self.write("package.json", "{broken")
        problems, warnings = self.parity()
        self.assertEqual(problems, [])
        self.assertIn("package.json을 JSON으로 읽지 못해", warnings[0])
        self.write("package.json", json.dumps({"engines": {"node": "latest"}}))
        problems, warnings = self.parity(runtime=(22, 0, 0))
        self.assertEqual(problems, [])
        self.assertIn("해석하지 못해", warnings[0])

    def test_area_dir_and_tool_versions(self):
        """T6"""
        self.write(".nvmrc", "22\n")
        self.write("web/.tool-versions", "java 21\nnodejs 20.1.0\n")
        self.write("web/web.Dockerfile", "FROM node:22\n")
        [problem], _ = self.parity(areas=["web"])
        self.assertEqual(problem, "고정 버전이 서로 다르다: .nvmrc 22, web/.tool-versions 20.1.0, web/web.Dockerfile:1 22")
        self.assertEqual(self.parity()[0], [])  # 영역으로 등록하지 않은 디렉터리는 보지 않는다

    def test_semver_ranges(self):
        """T7"""
        cases = [
            ("^22.22.0", (22, 22, 0), True), ("^22.22.0", (22, 21, 9), False), ("^22.22.0", (23, 0, 0), False),
            ("^0.2.3", (0, 2, 9), True), ("^0.2.3", (0, 3, 0), False), ("^0.0.3", (0, 0, 4), False),
            ("~20.19", (20, 19, 5), True), ("~20.19.1", (20, 20, 0), False), ("~20", (20, 9, 0), True),
            (">=20.19.0 <21", (20, 99, 0), True), (">= 20.19.0 < 21", (21, 0, 0), False),
            ("20 || 22", (22, 1, 0), True), ("20 || 22", (21, 0, 0), False),
            ("20.x", (20, 3, 0), True), ("22.X.x", (23, 0, 0), False), ("*", (4, 0, 0), True), ("", (4, 0, 0), True),
            ("18 - 20", (20, 9, 9), True), ("18 - 20", (21, 0, 0), False), ("18.1 - 20.2.3", (20, 2, 4), False),
            (">20", (21, 0, 0), True), (">20", (20, 9, 0), False), ("<=20", (20, 9, 0), True), ("v22.1.0", (22, 1, 0), True),
        ]
        for text, version, expected in cases:
            with self.subTest(range=text, version=version):
                self.assertEqual(verify.satisfies(version, verify.parse_range(text)), expected)
        for text in ("latest", ">=", "22 - ", "^a"):
            with self.subTest(bad=text):
                with self.assertRaises(ValueError):
                    verify.parse_range(text)


class VerifyLoadTest(unittest.TestCase):
    def test_broken_common_is_exit_2(self):
        """리뷰 B F3"""
        import tempfile
        from tempdirs import remove_tree
        tmp = Path(tempfile.mkdtemp(prefix="harness-verify-"))
        self.addCleanup(remove_tree, tmp)
        (tmp / "bad.py").write_text("def (:\n", encoding="utf-8")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            code = verify.run(["--project", str(tmp), "--base", "HEAD", "--common", str(tmp / "bad.py")])
        self.assertEqual(code, 2)
        self.assertIn("읽을 수 없다", err.getvalue())


class FragmentTest(unittest.TestCase):
    def test_verify_fragment_header_and_manifest(self):
        """T9"""
        text = (ROOT / "core" / "ci" / "gitlab" / "verify.yml").read_text(encoding="utf-8")
        for needle in ("include:", "- remote:", "HARNESS_VERIFY_IMAGE", "HARNESS_VERIFY_PARITY", "필요 조건:", "예외:",
                       "harness-verify:",
                       ".harness/verify/verify_changed.py"):
            self.assertIn(needle, text)
        self.assertIn("CI_MERGE_REQUEST_DIFF_BASE_SHA", text)  # fork MR도 대상 쪽 기준과 비교한다(리뷰 B F2)
        self.assertNotIn("origin/$CI_MERGE_REQUEST_TARGET_BRANCH_NAME", text)

    def test_init_installs_verify_for_gitlab_only(self):
        """리뷰 B F4: 실제 init·check로 GitLab 소비자에만 설치되고 드리프트를 본다"""
        import tempfile
        from test_harness import run
        from tempdirs import remove_tree
        tmp = Path(tempfile.mkdtemp(prefix="harness-verify-init-"))
        self.addCleanup(remove_tree, tmp)
        gitlab, github = tmp / "gl", tmp / "gh"
        self.assertEqual(run(["init", str(gitlab), "--platform", "gitlab", "--tracker", "jira",
                              "--issue-prefix", "DEMO"])[0], 0)
        installed = gitlab / ".harness" / "verify" / "verify_changed.py"
        self.assertEqual(installed.read_bytes(), (ROOT / "core" / "ci" / "verify" / "verify_changed.py").read_bytes())
        self.assertEqual(run(["check", str(gitlab)])[0], 0)
        installed.write_text("# 변조\n", encoding="utf-8")
        code, out = run(["check", str(gitlab)])
        self.assertEqual(code, 1)
        self.assertIn("불일치: .harness/verify/verify_changed.py", out)
        self.assertEqual(run(["init", str(github), "--platform", "github", "--tracker", "github"])[0], 0)
        # GitHub 대상에는 MR 기록 요약(#123)만 생기고 GitLab CI 조각이 실행하는 검증 코드는 없다
        self.assertFalse((github / ".harness" / "verify").exists())
        self.assertTrue((github / ".harness" / "summary.py").is_file())


if __name__ == "__main__":
    unittest.main()
