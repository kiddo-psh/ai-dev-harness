"""`harness lint-plans` 테스트. 플랜·리뷰 fixture는 모두 합성이다."""

import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "lint_plans"
SPEC = importlib.util.spec_from_file_location("harness_lint", ROOT / "bin" / "harness.py")
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)

GITHUB_CONFIG = {"project_name": "t", "platform": "github", "tracker": "github",
                 "default_branch": "main", "integration_branch": "main"}


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def kit_spec(rel, number, key):
    return harness.load_lint_spec(ROOT, GITHUB_CONFIG, rel, number, key)


PLAN_SPEC = kit_spec(harness.PLAN_TEMPLATE, "3", "acceptance")
REVIEW_SPEC = kit_spec(harness.REVIEW_TEMPLATE, "6", "measurement")


def lint_plan(text):
    return harness.lint_document(text, PLAN_SPEC, "plan")


def lint_review(text):
    return harness.lint_document(text, REVIEW_SPEC, "review")


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = harness.main(argv)
    return code, out.getvalue(), err.getvalue()


class PlanLintTest(unittest.TestCase):
    def test_valid_plan_passes(self):  # T1
        self.assertEqual(lint_plan(fixture("plan.md")), ([], []))

    def test_unchosen_tier(self):  # T2
        unchosen = fixture("plan.md").replace("**표준**", "**엄격 | 표준 | 경량**")
        failures, _ = lint_plan(unchosen)
        self.assertEqual(len(failures), 1)
        self.assertIn("엄격 | 표준 | 경량", failures[0])
        no_line = fixture("plan.md").replace("> 판정: **표준** · 트리거: 없음\n", "")
        failures, _ = lint_plan(no_line)
        self.assertEqual(failures, ["판정 줄(`판정:`)이 없다"])

    def test_tier_literal_outside_tier_line_is_fine(self):
        text = fixture("plan.md").replace("- 없음\n", "- 본문의 `엄격 | 표준 | 경량` 언급\n", 1)
        self.assertEqual(lint_plan(text), ([], []))

    def test_missing_section(self):  # T3
        text = fixture("plan.md").replace("## 4. 미확정 항목\n", "")
        failures, _ = lint_plan(text)
        self.assertEqual(failures, ["절 누락: ## 4. 미확정 항목"])

    def test_heading_annotation_ignored(self):  # T4
        text = (fixture("plan.md")
                .replace("## 6. 테스트 목록 변경 기록 (구현 단계에서 추기)", "## 6. 테스트 목록 변경 기록")
                .replace("## 7. 결정 기록 (플랜 승인·플랜 이탈)", "## 7.  결정 기록 (다른 주석)"))
        self.assertEqual(lint_plan(text), ([], []))

    def test_empty_acceptance_table(self):  # T5
        rows = "| T1 | `XTest.test_a` | 입력 `a \\| b` | 종료 0 |\n| T2 | `XTest.test_b` | 잘못된 입력 | 종료 2 |\n"
        base = fixture("plan.md")
        self.assertIn(rows, base)
        cases = {
            "no rows": (base.replace(rows, ""), "데이터 행이 없다"),
            "template row": (base.replace(rows, "| T1 | | | |\n"), "빈 인수 테스트 행: T1"),
            "other empty row": (base.replace(rows, rows + "| T3 |  |  |  |\n"), "빈 인수 테스트 행: T3"),
        }
        for name, (text, expected) in cases.items():
            with self.subTest(name):
                failures, _ = lint_plan(text)
                self.assertEqual(len(failures), 1, failures)
                self.assertIn(expected, failures[0])
        section = base.split("## 3. 인수 테스트 목록\n")[1].split("## 4.")[0]
        failures, _ = lint_plan(base.replace(section, "\n표 없음\n\n"))
        self.assertEqual(failures, ["## 3. 인수 테스트 목록: 인수 테스트 표가 없다"])

    def test_placeholder_warning(self):  # T6
        text = fixture("plan.md").replace("근거: 합성 fixture", "근거: <한 줄>")
        failures, warnings = lint_plan(text)
        self.assertEqual(failures, [])
        self.assertEqual(warnings, ["자리표시자가 남았다: <한 줄>"])

    def test_placeholders_come_from_template(self):
        self.assertIn("<한 줄>", PLAN_SPEC["placeholders"])
        self.assertNotIn("<key>", PLAN_SPEC["placeholders"])
        self.assertIn("<한 줄 요지>", REVIEW_SPEC["placeholders"])


class ReviewLintTest(unittest.TestCase):
    def test_valid_review_passes(self):  # T7
        self.assertEqual(lint_review(fixture("review.md")), ([], []))

    def test_empty_measurement(self):  # T8
        base = fixture("review.md")
        text = base.replace("| 리뷰 세션 모델 | 합성 |", "| 리뷰 세션 모델 |  |")
        failures, _ = lint_review(text)
        self.assertEqual(failures, ["## 6. 측정 칸: 측정 칸이 비었다: 리뷰 세션 모델"])
        post_merge = base.replace("(병합 후 기입) | 병합 전 |", "(병합 후 기입) | |")
        failures, _ = lint_review(post_merge)
        self.assertEqual(len(failures), 1)
        table = base.split("| 항목 | 값 |\n| --- | --- |\n")[1]
        failures, _ = lint_review(base.replace(table, ""))
        self.assertEqual(failures, ["## 6. 측정 칸: 측정 표에 데이터 행이 없다"])

    def test_missing_section(self):  # T9
        text = fixture("review.md").replace("## 5. 단위 간 정합성 (마지막 1회)\n", "")
        failures, _ = lint_review(text)
        self.assertEqual(failures, ["절 누락: ## 5. 단위 간 정합성"])

    def test_plan_checks_not_applied_to_review(self):
        failures, _ = lint_review(fixture("review.md").replace("2026-10-02.", "판정: 엄격 | 표준 | 경량"))
        self.assertEqual(failures, [])


class TableTest(unittest.TestCase):
    def test_delimiter_variants(self):  # T10
        for delimiter in ["|---|---|", "| --- | --- |", "|:---|---:|", "| :---: | :-: |", "--- | ---",
                          "|-|-|"]:
            with self.subTest(delimiter):
                header = "| a | b |" if delimiter.startswith("|") else "a | b"
                lines = [header, delimiter, "| 1 | 2 |", "| 3 | 4 |", "", "| x | y |"]
                self.assertEqual(harness.first_table(lines), [["1", "2"], ["3", "4"]])

    def test_not_a_table(self):
        self.assertIsNone(harness.first_table(["| a | b |", "| 1 | 2 |"]))
        self.assertIsNone(harness.first_table(["a", "---", "b"]))

    def test_escaped_pipe(self):  # T11
        self.assertEqual(harness.table_cells("| T1 | `a \\| b` | c |"), ["T1", "`a \\| b`", "c"])
        self.assertEqual(harness.table_cells("| T1 | | | |"), ["T1", "", "", ""])

    def test_code_fence_ignored(self):  # T12
        text = fixture("plan.md").replace("## 0. 작업 정보\n", "")
        text = text.replace("```text\n", "```text\n## 0. 작업 정보\n")
        failures, _ = lint_plan(text)
        self.assertEqual(failures, ["절 누락: ## 0. 작업 정보"])


class SelectTest(unittest.TestCase):
    def test_classification(self):  # T13
        names = ["38.md", "38-review.md", "38-review-A.md", "38-review-B.md", "1-mapping.md",
                 "20-self-review.md", "m2-decisions.md", "notes.txt"]
        groups = harness.classify_plan_files(names, GITHUB_CONFIG, None)
        # 엄격 단계의 -review.md는 A·B 합본 대조표라 제외한다(영역 AGENTS.md 4장)
        self.assertEqual(groups, {"plan": ["38.md"], "review": ["38-review-A.md", "38-review-B.md"],
                                  "excluded": ["1-mapping.md", "20-self-review.md", "38-review.md"],
                                  "ignored": ["m2-decisions.md", "notes.txt"]})

    def test_key_selection(self):
        names = ["38.md", "38-review.md", "380.md", "3-review.md", "38-self-review.md", "1-mapping.md"]
        groups = harness.classify_plan_files(names, GITHUB_CONFIG, "38")
        self.assertEqual(groups, {"plan": ["38.md"], "review": ["38-review.md"],
                                  "excluded": ["38-self-review.md"], "ignored": []})

    def test_combined_review_only_with_a_or_b(self):
        groups = harness.classify_plan_files(["5.md", "5-review.md", "5-review-A.md", "6-review.md"], GITHUB_CONFIG, None)
        self.assertEqual(groups["review"], ["5-review-A.md", "6-review.md"])
        self.assertEqual(groups["excluded"], ["5-review.md"])

    def test_jira_keys(self):  # T14
        config = {**GITHUB_CONFIG, "tracker": "jira", "issue_prefix": "ABC"}
        groups = harness.classify_plan_files(["ABC-5.md", "abc-5-review.md", "38.md", "XYZ-1.md"], config, None)
        self.assertEqual(groups["plan"], ["ABC-5.md"])
        self.assertEqual(groups["review"], ["abc-5-review.md"])
        self.assertEqual(groups["ignored"], ["38.md", "XYZ-1.md"])


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / "harness.json").write_text(json.dumps(GITHUB_CONFIG), encoding="utf-8")
        shutil.copytree(ROOT / "docs" / "templates", self.repo / "docs" / "templates")
        self.plans = self.repo / "plans"
        self.plans.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        (self.plans / name).write_text(text, encoding="utf-8")

    def lint(self, *argv):
        return run(["lint-plans", *argv, "--target", str(self.repo)])

    def test_exit_codes(self):  # T15
        self.write("7.md", fixture("plan.md"))
        self.write("7-review.md", fixture("review.md"))
        code, out, _ = self.lint()
        self.assertEqual(code, 0, out)
        self.assertIn("통과: plans/7.md (플랜)", out)
        self.assertIn("파일 2개, 실패 0건, 경고 0건", out)

        self.write("8.md", fixture("plan.md").replace("근거: 합성 fixture", "근거: <한 줄>"))
        code, out, _ = self.lint()
        self.assertEqual(code, 0, out)
        self.assertIn("경고: plans/8.md (플랜)", out)

        self.write("9-review-A.md", fixture("review.md").replace("| 리뷰 세션 모델 | 합성 |", "| 리뷰 세션 모델 | |"))
        code, out, _ = self.lint()
        self.assertEqual(code, 1, out)
        self.assertIn("실패: plans/9-review-A.md (리뷰)", out)
        self.assertIn("  실패: ## 6. 측정 칸: 측정 칸이 비었다: 리뷰 세션 모델", out)

    def test_key_filter(self):  # T16
        self.write("7.md", fixture("plan.md"))
        self.write("7-review-B.md", fixture("review.md"))
        self.write("9.md", "# 깨진 플랜\n")
        self.write("7-mapping.md", "# 대조표\n")
        code, out, _ = self.lint("7")
        self.assertEqual(code, 0, out)
        self.assertIn("plans/7-review-B.md", out)
        self.assertNotIn("9.md", out)
        self.assertIn("제외(-mapping·-self-review·엄격 합본 -review.md): 7-mapping.md", out)
        code, _, _ = self.lint()
        self.assertEqual(code, 1)

    def test_errors(self):  # T17
        self.write("7.md", fixture("plan.md"))
        for argv, message in [(["8"], "키 8"), (["../x"], "키는"), (["a/b"], "키는")]:
            with self.subTest(argv):
                code, _, err = self.lint(*argv)
                self.assertEqual(code, 2)
                self.assertIn(message, err)
        (self.repo / "harness.json").unlink()
        code, _, err = self.lint()
        self.assertEqual(code, 2)
        self.assertIn("설정 파일이 없다", err)

    def test_no_plans_dir(self):  # T18
        self.plans.rmdir()
        code, out, _ = self.lint()
        self.assertEqual(code, 0)
        self.assertIn("검사할 파일 없음", out)

    def test_template_from_target(self):  # T19
        self.write("7.md", fixture("plan.md"))
        plan_template = self.repo / "docs" / "templates" / "plan.md"
        plan_template.write_text(plan_template.read_text(encoding="utf-8") + "\n## 8. 추가 절\n", encoding="utf-8")
        code, out, _ = self.lint()
        self.assertEqual(code, 1)
        self.assertIn("절 누락: ## 8. 추가 절", out)
        shutil.rmtree(self.repo / "docs")  # 대상 템플릿이 없으면 키트 원본을 대상 설정으로 렌더한다
        code, out, _ = self.lint()
        self.assertEqual(code, 0, out)
        self.assertIn("템플릿: 키트 docs/templates/plan.md", out)

    def test_template_without_numbered_section_is_error(self):
        self.write("7.md", fixture("plan.md"))
        plan_template = self.repo / "docs" / "templates" / "plan.md"
        plan_template.write_text("# 플랜\n\n## 개요\n", encoding="utf-8")
        code, _, err = self.lint()
        self.assertEqual(code, 2)
        self.assertIn("3장 절이 없다", err)

    def test_files_not_modified(self):
        self.write("7.md", fixture("plan.md").replace("**표준**", "**엄격 | 표준 | 경량**"))
        before = (self.plans / "7.md").read_bytes()
        self.lint()
        self.assertEqual((self.plans / "7.md").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
