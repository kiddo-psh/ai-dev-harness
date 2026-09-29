"""bin/harness.py 단위·리허설 테스트. `python -m unittest discover tests -v`로 실행한다."""

import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
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


class SelfApplicationTest(unittest.TestCase):
    """키트 저장소 자신이 자기 템플릿과 일치해야 한다(드리프트 0)."""

    def test_self_check_is_clean(self):
        code, out = run(["check", "--self"])
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
