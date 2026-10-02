#!/usr/bin/env python3
"""검증된 Claude 리뷰를 중복·stale 방지 후 GitLab MR 댓글로 등록한다."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import stat
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

_COMMON_SPEC = importlib.util.spec_from_file_location(
    "harness_review_common", Path(__file__).resolve().with_name("review_common.py"))
common = importlib.util.module_from_spec(_COMMON_SPEC)
_COMMON_SPEC.loader.exec_module(common)

# 스크립트는 대상 저장소의 `.harness/claude-review/`에 있다. 저장소 루트의 harness.json이 정책이다.
ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "harness.json"
MAX_FILE_BYTES = 768 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_NOTES = 1000
MAX_COMMENT_BYTES = 256 * 1024
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_SEVERITIES = {"BLOCKER", "HIGH", "MEDIUM", "LOW"}
MARKER_VERSION = "v1"


PublishError = common.ReviewError


class GitLabClient:
    def __init__(self, api_url: str, project_id: int, token: str, opener=urlopen,
                 target_branch: str = "", timeout: int = 20):
        if not api_url.startswith("https://"):
            raise PublishError("INVALID_API_URL")
        self.api_url = api_url.rstrip("/")
        self.project_id = project_id
        self.token = token
        self.opener = opener
        self.target_branch = target_branch
        self.timeout = timeout

    def request(self, method: str, path: str, payload: dict[str, object] | None = None,
                query: dict[str, object] | None = None):
        url = self.api_url + path
        if query:
            url += "?" + urlencode(query)
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"PRIVATE-TOKEN": self.token, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with self.opener(request, timeout=self.timeout) as response:
                length = response.headers.get("Content-Length")
                if length and int(length) > MAX_RESPONSE_BYTES:
                    raise PublishError("GITLAB_RESPONSE_TOO_LARGE")
                response_body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(response_body) > MAX_RESPONSE_BYTES:
                    raise PublishError("GITLAB_RESPONSE_TOO_LARGE")
                return json.loads(response_body), response.headers
        except PublishError:
            raise
        except HTTPError as error:
            if error.code in (401, 403):
                raise PublishError("GITLAB_AUTHORIZATION_FAILED") from None
            if error.code == 404:
                raise PublishError("MR_OR_NOTE_NOT_FOUND") from None
            if error.code == 429:
                raise PublishError("GITLAB_RATE_LIMITED") from None
            raise PublishError("GITLAB_API_FAILED") from None
        except (URLError, TimeoutError):
            raise PublishError("GITLAB_CONNECTION_FAILED") from None
        except (ValueError, TypeError, json.JSONDecodeError):
            raise PublishError("INVALID_GITLAB_RESPONSE") from None

    def mr_path(self, iid: int) -> str:
        project = quote(str(self.project_id), safe="")
        return f"/projects/{project}/merge_requests/{iid}"

    def current_sha(self, iid: int) -> str:
        metadata, _ = self.request("GET", self.mr_path(iid))
        if (not isinstance(metadata, dict) or metadata.get("state") != "opened"
                or not self.target_branch
                or metadata.get("target_branch") != self.target_branch
                or metadata.get("source_project_id") != self.project_id
                or metadata.get("target_project_id") != self.project_id
                or not isinstance(metadata.get("sha"), str)
                or not SHA_PATTERN.fullmatch(metadata["sha"])):
            raise PublishError("MR_NO_LONGER_ELIGIBLE")
        return metadata["sha"]

    def current_user_id(self) -> int:
        user, _ = self.request("GET", "/user")
        if not isinstance(user, dict) or type(user.get("id")) is not int or user["id"] <= 0:
            raise PublishError("INVALID_GITLAB_RESPONSE")
        return user["id"]

    def has_duplicate(self, iid: int, marker: str, author_id: int) -> bool:
        page = 1
        seen = 0
        while True:
            notes, headers = self.request("GET", self.mr_path(iid) + "/notes",
                                          query={"per_page": 100, "page": page, "sort": "asc"})
            if not isinstance(notes, list):
                raise PublishError("INVALID_GITLAB_RESPONSE")
            seen += len(notes)
            if seen > MAX_NOTES:
                raise PublishError("NOTE_SCAN_LIMIT_EXCEEDED")
            for note in notes:
                if not isinstance(note, dict):
                    raise PublishError("INVALID_GITLAB_RESPONSE")
                author = note.get("author")
                if (isinstance(author, dict) and author.get("id") == author_id
                        and isinstance(note.get("body"), str) and marker in note["body"]):
                    return True
            next_page = headers.get("X-Next-Page", "")
            if not next_page:
                return False
            try:
                following_page = int(next_page)
            except (TypeError, ValueError):
                raise PublishError("INVALID_GITLAB_RESPONSE") from None
            if following_page <= page or following_page > MAX_NOTES:
                raise PublishError("INVALID_GITLAB_RESPONSE")
            page = following_page

    def create_note(self, iid: int, body: str) -> int:
        note, _ = self.request("POST", self.mr_path(iid) + "/notes", {"body": body})
        if (not isinstance(note, dict) or type(note.get("id")) is not int
                or note["id"] <= 0 or note.get("body") != body):
            raise PublishError("INVALID_NOTE_RESPONSE")
        return note["id"]

    def delete_note(self, iid: int, note_id: int) -> None:
        project = quote(str(self.project_id), safe="")
        path = f"/projects/{project}/merge_requests/{iid}/notes/{note_id}"
        # GitLab은 성공한 DELETE에 빈 본문을 반환할 수 있어 별도 요청 처리를 사용한다.
        url = self.api_url + path
        request = Request(url, headers={"PRIVATE-TOKEN": self.token}, method="DELETE")
        try:
            with self.opener(request, timeout=self.timeout) as response:
                response.read(MAX_RESPONSE_BYTES + 1)
        except (HTTPError, URLError, TimeoutError, OSError):
            raise PublishError("STALE_REVIEW_CLEANUP_FAILED") from None


def positive_int(value: str, code: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise PublishError(code) from None
    if number <= 0:
        raise PublishError(code)
    return number


def trusted_context(env: dict[str, str], policy: dict) -> bool:
    return common.trusted_context(env, policy)


def load_private_json(path: Path, missing_code: str) -> object:
    try:
        details = path.lstat()
    except OSError:
        raise PublishError(missing_code) from None
    if not stat.S_ISREG(details.st_mode) or path.is_symlink():
        raise PublishError("UNSAFE_REVIEW_FILE")
    if os.name != "nt" and (details.st_uid != os.getuid() or details.st_mode & 0o077):
        raise PublishError("UNSAFE_REVIEW_PERMISSIONS")
    if details.st_size > MAX_FILE_BYTES:
        raise PublishError("REVIEW_FILE_TOO_LARGE")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise PublishError("INVALID_REVIEW_FILE") from None


def validate_files(payload: object, review: object, iid: int, sha: str, target_branch: str) -> None:
    if not isinstance(payload, dict) or payload.get("untrusted_data") is not True:
        raise PublishError("INVALID_REVIEW_FILE")
    mr, files = payload.get("merge_request"), payload.get("files")
    if (not isinstance(mr, dict) or mr.get("iid") != iid or mr.get("sha") != sha
            or not target_branch or mr.get("target_branch") != target_branch
            or not isinstance(files, list)):
        raise PublishError("REVIEW_INPUT_MISMATCH")
    allowed_files = {item.get("new_path") for item in files if isinstance(item, dict)}
    if (not isinstance(review, dict) or set(review) != {"summary", "findings"}
            or not isinstance(review["summary"], str) or not review["summary"].strip()
            or not isinstance(review["findings"], list) or len(review["findings"]) > 50):
        raise PublishError("INVALID_REVIEW_FILE")
    if len(review["summary"].encode("utf-8")) > 4096:
        raise PublishError("INVALID_REVIEW_FILE")
    expected = {"severity", "file", "line", "condition", "evidence", "recommendation"}
    for finding in review["findings"]:
        if (not isinstance(finding, dict) or set(finding) != expected
                or finding["severity"] not in ALLOWED_SEVERITIES
                or finding["file"] not in allowed_files
                or (finding["line"] is not None
                    and (type(finding["line"]) is not int or finding["line"] <= 0))):
            raise PublishError("INVALID_REVIEW_FILE")
        for key in ("file", "condition", "evidence", "recommendation"):
            if not isinstance(finding[key], str) or not finding[key].strip():
                raise PublishError("INVALID_REVIEW_FILE")


def marker(project_id: int, iid: int, sha: str, name: str = common.DEFAULTS["comment_marker"]) -> str:
    return f"<!-- {name}:{MARKER_VERSION} project={project_id} mr={iid} sha={sha} -->"


def inline_code(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    longest = max((len(group) for group in re.findall(r"`+", normalized)), default=0)
    fence = "`" * max(1, longest + 1)
    return f"{fence} {normalized} {fence}"


def action_category(severity: str) -> str:
    if severity in ("BLOCKER", "HIGH"):
        return "병합 전 수정"
    if severity == "MEDIUM":
        return "병합 전 확인"
    return "후속 작업 후보"


def merge_guidance(findings: list[dict[str, object]]) -> str:
    fix_count = sum(item["severity"] in ("BLOCKER", "HIGH") for item in findings)
    verify_count = sum(item["severity"] == "MEDIUM" for item in findings)
    follow_up_count = sum(item["severity"] == "LOW" for item in findings)
    if fix_count:
        conclusion = "현재 변경에 병합 전 수정 권장 항목이 있습니다."
    elif verify_count:
        conclusion = "병합 전 확인 항목의 처리 여부를 확인한 뒤 병합을 판단하세요."
    elif follow_up_count:
        conclusion = "즉시 병합을 막는 항목은 없으며 후속 작업 반영 여부를 확인하세요."
    else:
        conclusion = "현재 diff에서 근거가 충분한 병합 차단 항목을 찾지 못했습니다."
    return (f"- **병합 전 수정:** {fix_count}건\n"
            f"- **병합 전 확인:** {verify_count}건\n"
            f"- **후속 작업 후보:** {follow_up_count}건\n"
            f"- **판단:** {conclusion}")


def format_comment(review: dict[str, object], project_id: int, iid: int, sha: str,
                   changed_file_count: int, marker_name: str = common.DEFAULTS["comment_marker"]) -> str:
    findings = review["findings"]
    if findings:
        result = f"⚠️ 문제 {len(findings)}건 발견"
    else:
        result = "✅ 발견된 문제 없음"
    severity_counts = [f"{severity} {sum(item['severity'] == severity for item in findings)}"
                       for severity in ("BLOCKER", "HIGH", "MEDIUM", "LOW")
                       if any(item["severity"] == severity for item in findings)]
    parts = [marker(project_id, iid, sha, marker_name), "## 🤖 Claude 자동 코드 리뷰",
             f"**결과:** {result}  \n**검토 커밋:** `{sha[:12]}`  \n**변경 파일:** {changed_file_count}개"]
    if severity_counts:
        parts.append("**심각도:** " + " · ".join(severity_counts))
    if not findings:
        parts.extend(["### 검토 결과", "현재 변경에서 근거가 충분한 문제를 찾지 못했습니다."])
    else:
        parts.append("### 발견된 문제")
        for index, finding in enumerate(findings, 1):
            location = finding["file"]
            if finding["line"] is not None:
                location += ":" + str(finding["line"])
            parts.extend([
                f"#### {index}. [{finding['severity']} · {action_category(finding['severity'])}]",
                "**위치:** " + inline_code(location),
                "**문제와 근거:** " + inline_code(
                    finding["condition"] + " " + finding["evidence"]),
                "**권장 조치:** " + inline_code(finding["recommendation"]),
            ])
    parts.extend([
        "### 병합 판단 참고", merge_guidance(findings),
        "> 이 리뷰는 AI가 자동 생성했으며 승인이나 병합을 의미하지 않습니다.",
    ])
    body = "\n\n".join(parts)
    if len(body.encode("utf-8")) > MAX_COMMENT_BYTES:
        raise PublishError("COMMENT_TOO_LARGE")
    return body


def publish(client: GitLabClient, iid: int, sha: str, body: str,
            marker_name: str = common.DEFAULTS["comment_marker"]) -> str:
    if client.current_sha(iid) != sha:
        raise PublishError("STALE_REVIEW_REJECTED")
    author_id = client.current_user_id()
    review_marker = marker(client.project_id, iid, sha, marker_name)
    if client.has_duplicate(iid, review_marker, author_id):
        return "DUPLICATE_REVIEW_SKIPPED"
    # 댓글 목록 조회 중 Push가 발생했을 수 있으므로 POST 직전에 다시 확인한다.
    if client.current_sha(iid) != sha:
        raise PublishError("STALE_REVIEW_REJECTED")
    note_id = client.create_note(iid, body)
    # POST와 동시에 Push된 경우 방금 만든 AI 댓글만 제거한다.
    if client.current_sha(iid) != sha:
        client.delete_note(iid, note_id)
        raise PublishError("STALE_REVIEW_REMOVED")
    return "PASS"


def main() -> int:
    try:
        policy = common.load_policy(POLICY_PATH)
        if not trusted_context(os.environ, policy):
            raise PublishError("REJECTED_CI_CONTEXT")
        server = common.load_server_config(common.server_config_path(policy))
        token = os.environ.get("GITLAB_REVIEW_TOKEN", "")
        if not token or any(character.isspace() for character in token):
            raise PublishError("MISSING_OR_INVALID_TOKEN")
        project_id = positive_int(os.environ.get("CI_PROJECT_ID", ""), "INVALID_PROJECT_ID")
        iid = positive_int(os.environ.get("REVIEW_MR_IID", ""), "INVALID_MR_IID")
        sha = os.environ.get("REVIEW_MR_SHA", "")
        if not SHA_PATTERN.fullmatch(sha):
            raise PublishError("INVALID_MR_SHA")
        payload = load_private_json(common.workdir_path(server, "input.json"), "REVIEW_INPUT_NOT_FOUND")
        review = load_private_json(common.workdir_path(server, "review.json"), "REVIEW_RESULT_NOT_FOUND")
        validate_files(payload, review, iid, sha, policy["target_branch"])
        marker_name = policy["comment_marker"]
        body = format_comment(review, project_id, iid, sha, len(payload["files"]), marker_name)
        client = GitLabClient(os.environ.get("CI_API_V4_URL", ""), project_id, token,
                              target_branch=policy["target_branch"],
                              timeout=policy["timeouts"]["gitlab_seconds"])
        result = publish(client, iid, sha, body, marker_name)
        print("REVIEW_PUBLISH: " + result)
        return 0
    except PublishError as error:
        print("REVIEW_PUBLISH: " + error.code)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
