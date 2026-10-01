"""bin/harness.py 단위·리허설 테스트. `python -m unittest discover tests -v`로 실행한다."""

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("harness", ROOT / "bin" / "harness.py")
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)


def run(argv):
    out = io.StringIO()
    with redirect_stdout(out):
        code = harness.main(argv)
    return code, out.getvalue()


class RenderTest(unittest.TestCase):
    def test_placeholders_are_replaced(self):
        ctx = harness.build_context({
            "project_name": "demo", "platform": "gitlab", "tracker": "jira",
            "issue_prefix": "ABC123", "default_branch": "main", "integration_branch": "develop",
            "related_docs": [{"label": "규칙", "path": "docs/a.md"}],
        })
        text = harness.render("{{pr_noun}} {{issue_key_example}}\n{{related_docs}}", ctx)
        self.assertEqual(text, "MR ABC123-52\n- [규칙](docs/a.md)")

    def test_github_context(self):
        ctx = harness.build_context({
            "project_name": "demo", "platform": "github", "tracker": "github",
            "default_branch": "main", "integration_branch": "main", "related_docs": [],
        })
        self.assertEqual(ctx["pr_noun"], "PR")
        self.assertEqual(ctx["issue_key_example"], "#52")
        self.assertEqual(ctx["related_docs"], "")

    def test_unknown_placeholder_fails(self):
        ctx = harness.build_context({
            "project_name": "demo", "platform": "github", "tracker": "github",
            "default_branch": "main", "integration_branch": "main",
        })
        with self.assertRaises(harness.HarnessError):
            harness.render("{{no_such_key}}", ctx)

    def test_jira_requires_prefix(self):
        with self.assertRaises(harness.HarnessError):
            harness.validate_config({
                "project_name": "demo", "platform": "gitlab", "tracker": "jira",
                "default_branch": "main", "integration_branch": "develop",
            }, "test")

    def test_every_template_renders_for_both_platforms(self):
        for platform, tracker in (("gitlab", "jira"), ("github", "github")):
            config = {
                "project_name": "demo", "platform": platform, "tracker": tracker,
                "issue_prefix": "ABC123", "default_branch": "main",
                "integration_branch": "develop", "related_docs": harness.CONSUMER_RELATED_DOCS,
            }
            outputs = harness.render_all(config, self_mode=False)
            self.assertTrue(outputs)
            for dest, content in outputs.items():
                self.assertNotIn("{{", content, f"{dest}에 치환되지 않은 자리표시자가 남았다")


class InitAndCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="harness-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_init_then_check_is_clean_for_gitlab_jira(self):
        target = self.tmp / "consumer"
        code, _ = run(["init", str(target), "--platform", "gitlab", "--tracker", "jira",
                       "--issue-prefix", "DEMO"])
        self.assertEqual(code, 0)
        self.assertTrue((target / "AGENTS.md").is_file())
        self.assertTrue((target / ".gitlab" / "merge_request_templates" / "Default.md").is_file())
        self.assertFalse((target / ".github").exists())
        config = json.loads((target / "harness.json").read_text(encoding="utf-8"))
        self.assertEqual(config["harness_version"], harness.VERSION)
        self.assertIn("DEMO-52", (target / "docs" / "git-convention.md").read_text(encoding="utf-8"))

        code, out = run(["check", str(target)])
        self.assertEqual(code, 0, out)

    def test_init_github_writes_pull_request_template(self):
        target = self.tmp / "gh"
        code, _ = run(["init", str(target), "--platform", "github", "--tracker", "github"])
        self.assertEqual(code, 0)
        self.assertTrue((target / ".github" / "PULL_REQUEST_TEMPLATE.md").is_file())
        self.assertFalse((target / ".gitlab").exists())

    def test_init_refuses_to_overwrite_without_force(self):
        target = self.tmp / "existing"
        target.mkdir()
        (target / "AGENTS.md").write_text("mine", encoding="utf-8")
        code, _ = run(["init", str(target), "--tracker", "github", "--platform", "github"])
        self.assertEqual(code, 2)
        self.assertEqual((target / "AGENTS.md").read_text(encoding="utf-8"), "mine")

    def test_check_detects_drift(self):
        target = self.tmp / "drift"
        run(["init", str(target), "--platform", "github", "--tracker", "github"])
        agents = target / "AGENTS.md"
        agents.write_text(agents.read_text(encoding="utf-8") + "\n손으로 고친 줄\n", encoding="utf-8")
        code, out = run(["check", str(target)])
        self.assertEqual(code, 1)
        self.assertIn("불일치: AGENTS.md", out)


class AreaTestBase(unittest.TestCase):
    """루트 init을 마친 대상 저장소에서 영역 AGENTS.md를 다룬다."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="harness-area-"))
        self.target = self.tmp / "consumer"
        code, _ = run(["init", str(self.target), "--platform", "gitlab", "--tracker", "jira",
                       "--issue-prefix", "DEMO"])
        self.assertEqual(code, 0)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def init_area(self, *extra):
        return run(["init", str(self.target), "--area", "backend", *extra])

    def config(self):
        return json.loads((self.target / "harness.json").read_text(encoding="utf-8"))

    def area_text(self):
        return (self.target / "backend" / "AGENTS.md").read_text(encoding="utf-8")


class AreaInitTest(AreaTestBase):
    def test_area_file_rendered(self):
        code, _ = self.init_area("--verify-cmd", "./gradlew build")
        self.assertEqual(code, 0)
        text = self.area_text()
        self.assertIn("- `./gradlew build`", text)
        for i, trigger in enumerate(harness.DEFAULT_TRIGGERS, 1):
            self.assertIn(f"{i}. {trigger}", text)
        self.assertIn("plans/<Jira Issue Key>.md", text)
        self.assertIn("MR 본문", text)
        self.assertNotIn("{{", text)

    def test_area_recorded_in_config(self):
        before = self.config()
        self.init_area("--verify-cmd", "./gradlew build")
        after = self.config()
        self.assertEqual(after["areas"], [{"dir": "backend", "verify": ["./gradlew build"]}])
        for key, value in before.items():
            self.assertEqual(after[key], value)

    def test_trigger_override(self):
        self.init_area("--verify-cmd", "make test", "--trigger", "A 변경", "--trigger", "B 변경")
        text = self.area_text()
        self.assertIn("1. A 변경\n2. B 변경\n", text)
        for trigger in harness.DEFAULT_TRIGGERS:
            self.assertNotIn(trigger, text)

    def test_reinit_updates_entry(self):
        self.init_area("--verify-cmd", "old")
        code, _ = self.init_area("--verify-cmd", "new", "--force")
        self.assertEqual(code, 0)
        areas = self.config()["areas"]
        self.assertEqual(len(areas), 1)
        self.assertEqual(areas[0]["verify"], ["new"])
        self.assertIn("- `new`", self.area_text())

    def test_existing_file_needs_force(self):
        area = self.target / "backend"
        area.mkdir()
        (area / "AGENTS.md").write_text("mine", encoding="utf-8")
        code, _ = self.init_area("--verify-cmd", "make test")
        self.assertEqual(code, 2)
        self.assertEqual((area / "AGENTS.md").read_text(encoding="utf-8"), "mine")
        self.assertNotIn("areas", self.config())

    def test_requires_config(self):
        bare = self.tmp / "bare"
        bare.mkdir()
        err = io.StringIO()
        with redirect_stderr(err):
            code, _ = run(["init", str(bare), "--area", "backend", "--verify-cmd", "make test"])
        self.assertEqual(code, 2)
        self.assertIn("루트 init", err.getvalue())
        self.assertEqual(list(bare.iterdir()), [])

    def test_requires_verify_cmd(self):
        code, _ = self.init_area()
        self.assertEqual(code, 2)
        self.assertFalse((self.target / "backend").exists())

    def test_rejects_escaping_dir(self):
        for bad in ("../x", "a/../../x", "/abs", "C:\\abs", "C:/abs", ".", ""):
            with self.subTest(dir=bad):
                code, _ = run(["init", str(self.target), "--area", bad, "--verify-cmd", "t"])
                self.assertEqual(code, 2)
        self.assertFalse((self.tmp / "x").exists())
        self.assertNotIn("areas", self.config())

    def test_default_docs_do_not_reference_missing_files(self):
        self.init_area("--verify-cmd", "make test")
        text = self.area_text()
        self.assertIn(harness.NO_AREA_DOCS, text)
        self.assertNotIn("backend/README.md", text)

    def test_area_doc_rendered(self):
        self.init_area("--verify-cmd", "make test", "--area-doc", "docs/api/README.md")
        text = self.area_text()
        self.assertIn("- `docs/api/README.md`", text)
        self.assertNotIn(harness.NO_AREA_DOCS, text)

    def test_rejects_root_flags(self):
        cases = (["--config", "other.json"], ["--platform", "github"], ["--tracker", "github"],
                 ["--project-name", "x"], ["--issue-prefix", "X"],
                 ["--default-branch", "main"], ["--integration-branch", "main"])
        for extra in cases:
            with self.subTest(flag=extra[0]):
                code, _ = self.init_area("--verify-cmd", "t", *extra)
                self.assertEqual(code, 2)
        self.assertFalse((self.target / "backend").exists())
        self.assertNotIn("areas", self.config())

    def test_area_flags_need_area(self):
        code, _ = run(["init", str(self.tmp / "other"), "--verify-cmd", "t"])
        self.assertEqual(code, 2)
        self.assertFalse((self.tmp / "other").exists())


class ConfigTest(unittest.TestCase):
    BASE = {"project_name": "demo", "platform": "github", "tracker": "github",
            "default_branch": "main", "integration_branch": "main"}

    def test_invalid_areas_rejected(self):
        bad_areas = [
            "backend",
            [{"verify": ["t"]}],
            [{"dir": "backend"}],
            [{"dir": "backend", "verify": []}],
            [{"dir": "backend", "verify": [1]}],
            [{"dir": "backend", "verify": ["t"], "triggers": []}],
            [{"dir": "backend", "verify": ["t"], "docs": [""]}],
            [{"dir": "../backend", "verify": ["t"]}],
            [{"dir": "./backend", "verify": ["t"]}],
            [{"dir": "backend", "verify": ["t"]}, {"dir": "backend", "verify": ["u"]}],
            [{"dir": "backend", "verify": ["t"], "trigger": ["오타"]}],
        ]
        for areas in bad_areas:
            with self.subTest(areas=areas):
                with self.assertRaises(harness.HarnessError):
                    harness.validate_config({**self.BASE, "areas": areas}, "test")

    def test_valid_areas_accepted(self):
        harness.validate_config({**self.BASE, "areas": [
            {"dir": "apps/web", "verify": ["npm test"], "review_focus": ["접근성"]},
        ]}, "test")

    def test_invalid_hooks_rejected(self):
        bad_hooks = [
            [],
            {"protected_path": []},
            {"protected_paths": "x"},
            {"protected_paths": [{"pattern": "x", "mode": "warn"}]},
            {"protected_paths": [{"pattern": "", "mode": "ask"}]},
            {"protected_paths": [{"pattern": "x", "mode": "ask", "why": "오타"}]},
            {"protected_paths": [{"pattern": "x", "mode": "ask", "reason": ""}]},
            {"stop_verify": []},
            {"stop_verify": [1]},
            {"stop_timeout_sec": 0},
            {"stop_timeout_sec": 841},
            {"stop_timeout_sec": True},
            {"stop_timeout_sec": "60"},
            {"python": ""},
            {"python": 'py "x'},
            {"python": "C:\\py.exe"},
            {"python": "python\nrm"},
        ]
        for hooks in bad_hooks:
            with self.subTest(hooks=hooks):
                with self.assertRaises(harness.HarnessError):
                    harness.validate_config({**self.BASE, "hooks": hooks}, "test")

    def test_valid_hooks_accepted(self):
        harness.validate_config(self.BASE, "test")
        harness.validate_config({**self.BASE, "hooks": {
            "protected_paths": [{"pattern": "docs/api/**", "mode": "block", "reason": "API 계약"},
                                {"pattern": "infra/", "mode": "ask"}],
            "stop_verify": ["npm test"], "stop_timeout_sec": 840, "python": "py -3",
        }}, "test")
        harness.validate_config({**self.BASE, "hooks": {"protected_paths": []}}, "test")


class HookInstallTest(unittest.TestCase):
    HOOK_FILES = ("protect-paths.py", "stop-verify.py", "harness_common.py")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="harness-hook-install-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def init(self, name, *extra):
        target = self.tmp / name
        code, out = run(["init", str(target), *extra])
        self.assertEqual(code, 0, out)
        return target

    def test_init_installs_hooks(self):
        for platform, tracker in (("gitlab", "jira"), ("github", "github")):
            with self.subTest(platform=platform):
                target = self.init(platform, "--platform", platform, "--tracker", tracker,
                                   "--issue-prefix", "DEMO")
                text = (target / ".claude" / "settings.json").read_text(encoding="utf-8")
                self.assertNotIn("{{", text)
                settings = json.loads(text)["hooks"]
                self.assertEqual(settings["PreToolUse"][0]["matcher"], "Edit|Write|MultiEdit|NotebookEdit")
                self.assertEqual(settings["Stop"][0]["hooks"][0]["timeout"], 900)
                self.assertTrue(settings["PreToolUse"][0]["hooks"][0]["command"].startswith(
                    'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/protect-paths.py"'))
                for name in self.HOOK_FILES:
                    installed = (target / ".claude" / "hooks" / name).read_text(encoding="utf-8")
                    original = (harness.HOOKS_DIR / name).read_text(encoding="utf-8")
                    self.assertEqual(installed, original)
                code, out = run(["check", str(target)])
                self.assertEqual(code, 0, out)

    def test_check_detects_script_tamper(self):
        target = self.init("tamper", "--platform", "github", "--tracker", "github")
        script = target / ".claude" / "hooks" / "protect-paths.py"
        script.write_text(script.read_text(encoding="utf-8").replace("deny", "allow"), encoding="utf-8")
        code, out = run(["check", str(target)])
        self.assertEqual(code, 1)
        self.assertIn("불일치: .claude/hooks/protect-paths.py", out)

    def test_hook_python_rendered(self):
        target = self.init("py", "--platform", "github", "--tracker", "github")
        config_path = target / "harness.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["hooks"] = {"python": "python"}
        config_path.write_text(json.dumps(config), encoding="utf-8")
        code, out = run(["init", str(target), "--force"])
        self.assertEqual(code, 0, out)
        settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
        command = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertTrue(command.startswith('python "$CLAUDE_PROJECT_DIR/.claude/hooks/stop-verify.py"'))

    def test_existing_settings_need_force(self):
        target = self.tmp / "existing"
        (target / ".claude").mkdir(parents=True)
        (target / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
        code, _ = run(["init", str(target), "--platform", "github", "--tracker", "github"])
        self.assertEqual(code, 2)
        self.assertEqual((target / ".claude" / "settings.json").read_text(encoding="utf-8"), "{}")

    def test_installed_hook_runs_from_target(self):
        target = self.init("run", "--platform", "github", "--tracker", "github")
        payload = {"tool_name": "Write", "tool_input": {"file_path": str(target / "package-lock.json")}}
        result = subprocess.run(
            [sys.executable, str(target / ".claude" / "hooks" / "protect-paths.py")],
            input=json.dumps(payload).encode("utf-8"), capture_output=True, timeout=60,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(target)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        decision = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]
        self.assertEqual(decision, "deny")
        self.assertFalse((target / ".claude" / "hooks" / "__pycache__").exists())  # 대상에 부산물을 남기지 않는다


class AreaCheckTest(AreaTestBase):
    def setUp(self):
        super().setUp()
        code, _ = self.init_area("--verify-cmd", "./gradlew build")
        self.assertEqual(code, 0)
        self.agents = self.target / "backend" / "AGENTS.md"

    def test_clean_after_area_init(self):
        code, out = run(["check", str(self.target)])
        self.assertEqual(code, 0, out)

    def test_area_drift_detected(self):
        self.agents.write_text(self.area_text() + "\n손으로 고친 줄\n", encoding="utf-8")
        code, out = run(["check", str(self.target)])
        self.assertEqual(code, 1)
        self.assertIn("불일치: backend/AGENTS.md", out)

    def test_area_missing_detected(self):
        self.agents.unlink()
        code, out = run(["check", str(self.target)])
        self.assertEqual(code, 1)
        self.assertIn("없음:   backend/AGENTS.md", out)


class AreaTemplateTest(unittest.TestCase):
    LINE_BUDGET = 70

    def rendered(self):
        ctx = harness.build_context({
            "project_name": "demo", "platform": "gitlab", "tracker": "jira",
            "issue_prefix": "DEMO", "default_branch": "main", "integration_branch": "develop",
        })
        return harness.render_area({"dir": "backend", "verify": ["./gradlew build"]}, ctx)

    def test_line_budget(self):
        lines = self.rendered().splitlines()
        self.assertLessEqual(len(lines), self.LINE_BUDGET)

    def test_rules_are_tagged(self):
        """3장 이후의 규칙 목록 항목마다 강제 주체 표시가 있어야 한다."""
        text = self.rendered()
        body = text[text.index("## 3. 판정"):]
        rules = [line for line in body.splitlines() if line.startswith("- ")]
        self.assertTrue(rules)
        for line in rules:
            with self.subTest(rule=line[:40]):
                self.assertRegex(line, r"\[(hook|ci|사람)\]$")


class TierNameTest(unittest.TestCase):
    """판정 단계의 옛 이름(검증만·기본·게이트)이 템플릿에 남지 않아야 한다."""

    def test_no_old_tier_names(self):
        for path in harness.TEMPLATES_DIR.rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            for old in ("검증만", "게이트"):
                with self.subTest(file=path.name, word=old):
                    self.assertNotIn(old, text)


class SelfApplicationTest(unittest.TestCase):
    """키트 저장소 자신이 자기 템플릿과 일치해야 한다(드리프트 0)."""

    def test_self_check_is_clean(self):
        code, out = run(["check", "--self"])
        self.assertEqual(code, 0, out)

    def test_hooks_in_self_manifest(self):
        config = harness.load_config(ROOT / "harness.json")
        outputs = harness.render_all(config, self_mode=True)
        for dest in (".claude/settings.json", ".claude/hooks/protect-paths.py",
                     ".claude/hooks/stop-verify.py", ".claude/hooks/harness_common.py"):
            self.assertIn(dest, outputs)
        commands = [hook["command"] for groups in json.loads(outputs[".claude/settings.json"])["hooks"].values()
                    for group in groups for hook in group["hooks"]]
        self.assertEqual(len(commands), 2)
        for command in commands:
            self.assertTrue(command.startswith('python "'), command)  # Windows에서 python3은 Store 별칭이다
        # 리뷰 #16 B-F9: 종료 검증을 의미 없는 명령으로 약화하면 잡는다. 기준은 docs/contributing.md "검증"
        self.assertEqual(config["hooks"]["stop_verify"],
                         ["python -m unittest discover tests -q", "python bin/harness.py check --self"])
        verify = (ROOT / "docs" / "contributing.md").read_text(encoding="utf-8")
        self.assertIn("python -m unittest discover tests -v\npython bin/harness.py check --self\n", verify)


if __name__ == "__main__":
    unittest.main()
