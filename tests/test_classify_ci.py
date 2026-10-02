"""core/metrics/classify_ci.py와 `harness classify-ci` 테스트. 로그 fixture는 모두 합성이다."""

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "classify_ci"

SPEC = importlib.util.spec_from_file_location("classify_ci", ROOT / "core" / "metrics" / "classify_ci.py")
classify_ci = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(classify_ci)

HARNESS_SPEC = importlib.util.spec_from_file_location("harness_cli", ROOT / "bin" / "harness.py")
harness = importlib.util.module_from_spec(HARNESS_SPEC)
HARNESS_SPEC.loader.exec_module(harness)

FIELDS = {"job_id", "name", "stage", "failure_reason", "category", "matches"}


def job(job_id=1, name="build", status="failed", reason="script_failure", stage="test"):
    return {"id": job_id, "name": name, "stage": stage, "status": status, "failure_reason": reason}


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def rules(record):
    return {m["rule"] for m in record["matches"]}


class LogRuleTest(unittest.TestCase):
    CASES = [
        ("gradle-test.log", "test", "test.gradle"),
        ("jest.log", "test", "test.jest"),
        ("pytest.log", "test", "test.pytest"),
        ("prettier.log", "format", "format.prettier"),
        ("eslint.log", "format", "format.eslint"),
        ("gradle-test-and-spotless.log", "format", "format.spotless"),
        ("docker-pull.log", "infra", "infra.registry"),
        ("dns.log", "infra", "infra.dns"),
        ("npm-network.log", "infra", "infra.network"),
        ("oom.log", "infra", "infra.oom"),
        ("test-with-dns.log", "infra", "infra.dns"),
        ("timeout.log", "timeout", "timeout.job_execution"),
    ]

    def test_fixtures(self):
        for name, category, rule in self.CASES:
            with self.subTest(fixture=name):
                record = classify_ci.classify_job(job(), fixture(name))
                self.assertEqual(record["category"], category)
                self.assertIn(rule, rules(record))

    def test_lower_priority_matches_kept(self):
        record = classify_ci.classify_job(job(), fixture("gradle-test-and-spotless.log"))
        self.assertTrue({"format.spotless", "test.gradle"} <= rules(record))
        record = classify_ci.classify_job(job(), fixture("test-with-dns.log"))
        self.assertTrue({"infra.dns", "test.gradle"} <= rules(record))

    def test_line_numbers_and_counts(self):
        record = classify_ci.classify_job(job(), fixture("gradle-test.log"))
        gradle = next(m for m in record["matches"] if m["rule"] == "test.gradle")
        lines = fixture("gradle-test.log").split("\n")
        self.assertIn("FAILED", lines[gradle["line"] - 1])
        self.assertGreater(gradle["count"], 1)
        self.assertEqual(gradle["category"], "test")

    def test_unknown_log_unclassified(self):
        record = classify_ci.classify_job(job(), "$ make deploy\nsomething odd happened\n")
        self.assertEqual(record["category"], "unclassified")
        self.assertEqual(record["matches"], [])


class ReasonTest(unittest.TestCase):
    def test_timeout_reason(self):
        record = classify_ci.classify_job(job(reason="job_execution_timeout"), fixture("gradle-test.log"))
        self.assertEqual(record["category"], "timeout")
        self.assertEqual(record["matches"][0],
                         {"rule": "reason.job_execution_timeout", "category": "timeout", "line": None, "count": 1})
        self.assertIn("test.gradle", rules(record))

    def test_runner_reason(self):
        for reason in ("runner_system_failure", "stuck_or_timeout_failure", "api_failure"):
            with self.subTest(reason=reason):
                record = classify_ci.classify_job(job(reason=reason), None)
                expected = "timeout" if reason == "stuck_or_timeout_failure" else "infra"
                self.assertEqual(record["category"], expected)

    def test_script_failure_not_decisive(self):
        for reason in ("script_failure", "unknown_failure", None):
            with self.subTest(reason=reason):
                record = classify_ci.classify_job(job(reason=reason), None)
                self.assertEqual(record["category"], "unclassified")
                self.assertEqual(record["matches"], [])

    def test_security_job_name(self):
        record = classify_ci.classify_job(job(name="harness-secret-detection"), fixture("gitleaks.log"))
        self.assertEqual(record["category"], "security")
        self.assertIn("name.harness_job", rules(record))

    def test_name_beats_log(self):
        record = classify_ci.classify_job(job(name="harness-image-scan"), fixture("docker-pull.log"))
        self.assertEqual(record["category"], "security")
        self.assertIn("infra.registry", rules(record))

    def test_reason_beats_name(self):
        record = classify_ci.classify_job(job(name="harness-image-scan", reason="runner_system_failure"), None)
        self.assertEqual(record["category"], "infra")
        self.assertEqual(rules(record), {"reason.runner_system_failure", "name.harness_job"})


class MarkerTest(unittest.TestCase):
    def test_marker_category(self):
        trace = 'HARNESS_LINT_RESULT={"category": "format", "tool": "x"}\n' + fixture("gradle-test.log")
        record = classify_ci.classify_job(job(name="harness-lint"), trace)
        self.assertEqual(record["category"], "format")
        marker = next(m for m in record["matches"] if m["rule"] == "marker.HARNESS_LINT_RESULT")
        self.assertEqual((marker["line"], marker["category"]), (1, "format"))

    def test_reason_beats_marker(self):
        trace = 'X_RESULT={"category": "test"}\n'
        record = classify_ci.classify_job(job(reason="job_execution_timeout"), trace)
        self.assertEqual(record["category"], "timeout")

    def test_invalid_marker_ignored(self):
        for line in ('X_RESULT={"category": "format"',  # 깨진 JSON
                     'X_RESULT={"category": "style"}',
                     'X_RESULT={"category": "unclassified"}',
                     'X_RESULT=["format"]',
                     'x_result={"category": "format"}'):
            with self.subTest(line=line):
                record = classify_ci.classify_job(job(), line + "\n" + fixture("pytest.log"))
                self.assertEqual(record["category"], "test")
                self.assertFalse(any(r.startswith("marker.") for r in rules(record)))


class NormalizeTest(unittest.TestCase):
    def test_ansi_and_sections(self):
        trace = ("\x1b[0KRunning with gitlab-runner\x1b[0;m\n"
                 "section_start:1700000000:step_script\r\x1b[0K\x1b[0K\x1b[36;1mExecuting step\x1b[0;m\n"
                 "2026-10-02T01:02:03.456789Z 01O \x1b[31;1mKilled\x1b[0m\r\n"
                 "progress 10%\rprogress 100%\r\n")
        lines = classify_ci.normalize_lines(trace)
        self.assertEqual(lines[:4], ["Running with gitlab-runner", "Executing step", "Killed", "progress 100%"])
        record = classify_ci.classify_job(job(), trace)
        self.assertEqual(record["category"], "infra")
        oom = next(m for m in record["matches"] if m["rule"] == "infra.oom")
        self.assertEqual(oom["line"], 3)


class FilterTest(unittest.TestCase):
    def test_only_failed_jobs(self):
        jobs = [job(1, status="success"), job(2, status="canceled"), job(3, status="skipped"),
                job(4, status="failed", reason="job_execution_timeout"), job(5, status="manual")]
        records, skipped = classify_ci.classify_jobs(jobs, None)
        self.assertEqual([r["job_id"] for r in records], [4])
        self.assertEqual(skipped, 4)


class LoadTest(unittest.TestCase):
    def test_input_shapes(self):
        a, b = job(1), job(2)
        shapes = [json.dumps([a, b]), json.dumps([a]) + json.dumps([b]),
                  json.dumps([a]) + "\n" + json.dumps([b]),
                  json.dumps(a) + "\n" + json.dumps(b) + "\n", "﻿" + json.dumps([a, b])]
        for text in shapes:
            with self.subTest(text=text[:30]):
                self.assertEqual([j["id"] for j in classify_ci.load_jobs(text)], [1, 2])
        self.assertEqual(classify_ci.load_jobs(json.dumps(a))[0]["name"], "build")
        self.assertEqual(classify_ci.load_jobs(json.dumps({**a, "id": "7"}))[0]["id"], 7)

    def test_invalid_input(self):
        cases = ["", "not json", "[1]", json.dumps({"name": "x", "status": "failed"}),
                 json.dumps({"id": "../x", "status": "failed"}), json.dumps({"id": True, "status": "failed"}),
                 json.dumps({"id": -1, "status": "failed"}), json.dumps({"id": 1}),
                 json.dumps({"id": 1, "status": "failed", "name": 3})]
        for text in cases:
            with self.subTest(text=text), self.assertRaises(classify_ci.ClassifyError):
                classify_ci.load_jobs(text)


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = harness.main(argv)
    return code, out.getvalue(), err.getvalue()


class CliTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.traces = self.tmp / "traces"
        self.traces.mkdir()
        (self.traces / "11.log").write_text(fixture("jest.log"), encoding="utf-8")
        (self.traces / "12.log").write_text(fixture("gitleaks.log"), encoding="utf-8")
        self.jobs = self.tmp / "jobs.json"
        self.jobs.write_text(json.dumps([
            job(10, status="success"),
            job(11, name="web-test"),
            job(12, name="harness-secret-detection"),
            job(13, name="deploy", reason="runner_system_failure"),  # trace 없음
        ]), encoding="utf-8")

    def test_writes_jsonl(self):
        out = self.tmp / "out" / "result.jsonl"
        code, stdout, stderr = run_cli(["classify-ci", "--jobs", str(self.jobs),
                                        "--trace-dir", str(self.traces), "--out", str(out)])
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertIn("3개", stderr)
        records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(r["job_id"], r["category"]) for r in records],
                         [(11, "test"), (12, "security"), (13, "infra")])
        for record in records:
            self.assertEqual(set(record), FIELDS)

    def test_stdout_without_trace_dir(self):
        code, stdout, _ = run_cli(["classify-ci", "--jobs", str(self.jobs)])
        self.assertEqual(code, 0)
        records = [json.loads(line) for line in stdout.splitlines()]
        self.assertEqual([r["category"] for r in records], ["unclassified", "security", "infra"])

    def test_errors(self):
        bad = self.tmp / "bad.json"
        bad.write_text("{", encoding="utf-8")
        for argv in (["classify-ci", "--jobs", str(self.tmp / "none.json")],
                     ["classify-ci", "--jobs", str(self.jobs), "--trace-dir", str(self.tmp / "none")],
                     ["classify-ci", "--jobs", str(bad)]):
            with self.subTest(argv=argv):
                code, stdout, stderr = run_cli(argv)
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertIn("오류:", stderr)


if __name__ == "__main__":
    unittest.main()
