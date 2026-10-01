"""core/ci/gitlab/ 보안 검사 조각의 구조 규칙. 동작은 GitLab MR 파이프라인에서 확인한다.

표준 라이브러리에 YAML 파서가 없으므로 텍스트 수준에서 본다. 조각은 최상위 job 키 아래에 두 칸
들여쓰기로 쓴다는 형식을 전제로 한다.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GITLAB = ROOT / "core" / "ci" / "gitlab"
FRAGMENTS = ["secret-detection", "dependency-audit", "sast", "image-scan"]
BLOCKING = ["secret-detection", "dependency-audit", "image-scan"]


def text(name):
    return (GITLAB / f"{name}.yml").read_text(encoding="utf-8")


def header(name):
    lines = []
    for line in text(name).splitlines():
        if not line.startswith("#"):
            break
        lines.append(line)
    return "\n".join(lines)


def jobs(name):
    """{최상위 키: 본문}. 주석과 빈 줄은 뺀다."""
    result, current = {}, None
    for line in text(name).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        top = re.match(r"^([^\s#][^:]*):\s*$", line)
        if top:
            current = top.group(1)
            result[current] = []
        elif current is not None:
            result[current].append(line)
    return {k: "\n".join(v) for k, v in result.items()}


class CiFragmentTest(unittest.TestCase):
    def test_fragments_exist(self):
        for name in FRAGMENTS:
            self.assertTrue((GITLAB / f"{name}.yml").is_file(), name)

    def test_header_documents_usage(self):
        for name in FRAGMENTS:
            head = header(name)
            for needle in ("include:", "- remote: https://", f"core/ci/gitlab/{name}.yml", "필요 조건:", "예외:"):
                self.assertIn(needle, head, name)

    def test_images_pinned_by_digest(self):
        for name in FRAGMENTS:
            images = re.findall(r"^\s+name:\s*(\S+)", text(name), re.M)
            self.assertTrue(images, name)
            for image in images:
                self.assertRegex(image, r":[\w.-]+@sha256:[0-9a-f]{64}$", name)

    def test_blocking_jobs_not_allowed_to_fail(self):
        for name in BLOCKING:
            for job, body in jobs(name).items():
                self.assertNotIn("allow_failure", body, f"{name}:{job}")

    def test_sast_allows_only_findings_code(self):
        body = jobs("sast")["harness-sast"]
        self.assertRegex(body, r"allow_failure:\n\s+exit_codes: \[3\]")
        self.assertNotRegex(body, r"allow_failure:\s*true")
        self.assertRegex(body, r"0\|1\) ;;\n\s+\*\) fail ")  # semgrep의 0·1 밖은 실패
        self.assertIn('fail() { echo "harness: $*"; exit 2; }', body)
        self.assertEqual(len(re.findall(r"exit 3", body)), 1)  # 경고는 요약 단계 한 곳에서만
        self.assertIn(">/dev/null", body)  # 코드 줄을 그대로 보여 주는 기본 출력은 버린다
        self.assertIn("CI_MERGE_REQUEST_TARGET_BRANCH_SHA", body)
        self.assertIn('git merge-base --is-ancestor "$base" HEAD', body)
        self.assertIn('git diff --name-only "$base" HEAD -- "$c"', body)

    def test_no_error_swallowing(self):
        for name in FRAGMENTS:
            body = text(name)
            self.assertNotIn("set +e", body, name)
            self.assertNotIn("--exit-code 0", body, name)

    def test_tool_flags(self):
        secret = text("secret-detection")
        for flag in ("--redact", "--exit-code 1", "--remerge-diff", "merge-base --is-ancestor", "useDefault"):
            self.assertIn(flag, secret)
        self.assertIn("in_extend &&", secret)
        self.assertIn("/^[[:space:]]*\\[/ { in_extend=0 }", secret)
        for name in ("dependency-audit", "image-scan"):
            body = text(name)
            for flag in ("--exit-code 1", "--config /dev/null", "--ignore-unfixed", "--severity HIGH,CRITICAL"):
                self.assertIn(flag, body, name)
            self.assertRegex(body, r"cache:\n\s+key: harness-trivy\n\s+when: always", name)
        self.assertRegex(text("image-scan"), r"artifacts:\n\s+when: always\n\s+access: developer")
        image = text("image-scan")
        self.assertIn('set -- --input "$HARNESS_SCAN_ARCHIVE"', image)
        self.assertIn('if [ -n "${HARNESS_SCAN_IMAGE:-}" ]; then fail', image)
        self.assertIn('if [ ! -f "$HARNESS_SCAN_ARCHIVE" ] || [ ! -s "$HARNESS_SCAN_ARCHIVE" ]', image)

    def test_merge_request_only(self):
        for name in FRAGMENTS:
            for job, body in jobs(name).items():
                rules = re.search(r"^  rules:\n((?:    .*\n)+)", body + "\n", re.M)
                self.assertIsNotNone(rules, f"{name}:{job}")
                lines = rules.group(1).splitlines()
                self.assertEqual(lines[0], '    - if: $CI_PIPELINE_SOURCE == "merge_request_event"', f"{name}:{job}")
                rest = [line for line in lines[1:] if not re.match(r"^      (exists:|  - )", line)]
                self.assertEqual(rest, [], f"{name}:{job}")  # 다른 규칙이나 when으로 MR 밖에서 돌지 않는다

    def test_job_names_prefixed(self):
        for name in FRAGMENTS:
            keys = list(jobs(name))
            self.assertTrue(keys, name)
            for key in keys:
                self.assertTrue(key.startswith("harness-"), f"{name}:{key}")

    def test_scripts_fail_fast(self):
        for name in FRAGMENTS:
            for job, body in jobs(name).items():
                script = re.search(r"^  script:\n\s+- \|\n\s+(.+)", body, re.M)
                self.assertIsNotNone(script, f"{name}:{job}")
                self.assertRegex(script.group(1), r"^set -eu", f"{name}:{job}")


if __name__ == "__main__":
    unittest.main()
