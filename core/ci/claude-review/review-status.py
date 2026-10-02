#!/usr/bin/env python3
"""보호된 Claude 리뷰 Job의 실행 상태를 하나의 MR 댓글로 표시한다."""

from __future__ import annotations

import json
import os
import types
from pathlib import Path
import re
import stat
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

# 공통 코드는 원본에서 직접 컴파일한다. importlib 로더는 __pycache__의 바이트코드를 원본과 대조하지 않고
# 쓸 수 있어, check가 보지 않는 .pyc 하나로 신뢰 판정을 바꿀 수 있다.
_COMMON_PATH = Path(__file__).resolve().with_name("review_common.py")
common = types.ModuleType("harness_review_common")
common.__file__ = str(_COMMON_PATH)
sys.modules["harness_review_common"] = common
exec(compile(_COMMON_PATH.read_bytes(), str(_COMMON_PATH), "exec"), common.__dict__)

# 스크립트는 대상 저장소의 `.harness/claude-review/`에 있다. 저장소 루트의 harness.json이 정책이다.
ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "harness.json"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_STATUS_BYTES = 16 * 1024
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_STATES = {"running", "success", "failed", "canceled"}
MARKER_VERSION = "v1"


StatusError = common.ReviewError


class GitLabClient:
    def __init__(self, api_url: str, project_id: int, token: str, opener=urlopen,
                 target_branch: str = "", timeout: int = 20):
        if not api_url.startswith("https://"):
            raise StatusError("INVALID_API_URL")
        self.api_url = api_url.rstrip("/")
        self.project_id = project_id
        self.token = token
        self.opener = opener
        self.target_branch = target_branch
        self.timeout = timeout

    def request(self, method: str, path: str, payload: dict[str, object] | None = None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"PRIVATE-TOKEN": self.token, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(self.api_url + path, data=body, headers=headers, method=method)
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise StatusError("GITLAB_RESPONSE_TOO_LARGE")
                return json.loads(raw)
        except StatusError:
            raise
        except HTTPError as error:
            if error.code in (401, 403):
                raise StatusError("GITLAB_AUTHENTICATION_FAILED") from None
            if error.code == 404:
                raise StatusError("GITLAB_RESOURCE_NOT_FOUND") from None
            if error.code == 429:
                raise StatusError("GITLAB_RATE_LIMITED") from None
            raise StatusError("GITLAB_API_FAILED") from None
        except (URLError, TimeoutError, OSError, ValueError, TypeError,
                json.JSONDecodeError):
            raise StatusError("GITLAB_API_FAILED") from None

    def mr_path(self, iid: int) -> str:
        project = quote(str(self.project_id), safe="")
        return f"/projects/{project}/merge_requests/{iid}"

    def merge_request(self, iid: int) -> dict[str, object]:
        value = self.request("GET", self.mr_path(iid))
        if (not isinstance(value, dict) or value.get("iid") != iid
                or value.get("state") not in ("opened", "closed", "locked", "merged")
                or not self.target_branch
                or value.get("target_branch") != self.target_branch
                or value.get("source_project_id") != self.project_id
                or value.get("target_project_id") != self.project_id
                or not isinstance(value.get("sha"), str)
                or not SHA_PATTERN.fullmatch(value["sha"])):
            raise StatusError("MR_NO_LONGER_ELIGIBLE")
        return value

    def create_note(self, iid: int, body: str) -> int:
        value = self.request("POST", self.mr_path(iid) + "/notes", {"body": body})
        if (not isinstance(value, dict) or type(value.get("id")) is not int
                or value["id"] <= 0 or value.get("body") != body):
            raise StatusError("INVALID_NOTE_RESPONSE")
        return value["id"]

    def update_note(self, iid: int, note_id: int, body: str) -> None:
        value = self.request(
            "PUT", self.mr_path(iid) + f"/notes/{note_id}", {"body": body})
        if (not isinstance(value, dict) or value.get("id") != note_id
                or value.get("body") != body):
            raise StatusError("INVALID_NOTE_RESPONSE")


def positive_int(value: str, code: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise StatusError(code) from None
    if number <= 0:
        raise StatusError(code)
    return number


def trusted_context(env: dict[str, str], policy: dict) -> bool:
    return common.trusted_context(env, policy)


def validate_pipeline_url(project_url: str, pipeline_url: str, pipeline_id: int) -> str:
    expected = project_url.rstrip("/") + f"/-/pipelines/{pipeline_id}"
    if (not project_url.startswith("https://") or pipeline_url != expected
            or len(pipeline_url) > 255 or any(character.isspace() for character in pipeline_url)):
        raise StatusError("INVALID_PIPELINE_URL")
    return pipeline_url


def marker(project_id: int, iid: int, sha: str, pipeline_id: int,
           name: str = common.DEFAULTS["comment_marker"]) -> str:
    return (f"<!-- {name}-status:{MARKER_VERSION} project={project_id} mr={iid} "
            f"sha={sha} pipeline={pipeline_id} -->")


def format_comment(state: str, project_id: int, iid: int, sha: str, pipeline_id: int,
                   pipeline_url: str, stale: bool = False,
                   marker_name: str = common.DEFAULTS["comment_marker"]) -> str:
    labels = {
        "running": "🔄 리뷰 진행 중",
        "success": "✅ 리뷰 완료",
        "failed": "❌ 리뷰 실패",
        "canceled": "⏹️ 리뷰 취소",
    }
    details = {
        "running": "결과가 등록되기까지 약 2~3분 걸립니다.",
        "success": "리뷰 결과 댓글 등록을 완료했습니다.",
        "failed": "리뷰 생성 또는 댓글 등록에 실패했습니다. 파이프라인 로그를 확인해 주세요.",
        "canceled": "리뷰 Job이 취소되었습니다. 필요하면 다시 요청해 주세요.",
    }
    if stale:
        details["canceled"] = "새 Push 또는 MR 상태 변경으로 이 커밋의 리뷰를 중단했습니다."
    body = "\n\n".join([
        marker(project_id, iid, sha, pipeline_id, marker_name),
        "## 🤖 Claude 자동 코드 리뷰",
        f"**상태:** {labels[state]}  \n**검토 커밋:** `{sha[:12]}`",
        details[state],
        f"[파이프라인 #{pipeline_id}]({pipeline_url})",
    ])
    if len(body.encode("utf-8")) > MAX_STATUS_BYTES:
        raise StatusError("STATUS_COMMENT_TOO_LARGE")
    return body


def write_private_status(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, separators=(",", ":"))
        os.replace(temporary, path)
        path.chmod(0o600)
    except (OSError, TypeError, ValueError):
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise StatusError("STATUS_FILE_WRITE_FAILED") from None


def load_private_status(path: Path, iid: int, sha: str, pipeline_id: int) -> int:
    try:
        details = path.lstat()
    except OSError:
        raise StatusError("STATUS_FILE_NOT_FOUND") from None
    if (not stat.S_ISREG(details.st_mode) or path.is_symlink()
            or details.st_size > MAX_STATUS_BYTES
            or (os.name != "nt" and (details.st_uid != os.getuid() or details.st_mode & 0o077))):
        raise StatusError("UNSAFE_STATUS_FILE")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise StatusError("INVALID_STATUS_FILE") from None
    if (not isinstance(value, dict)
            or set(value) != {"iid", "sha", "pipeline_id", "note_id"}
            or value.get("iid") != iid or value.get("sha") != sha
            or value.get("pipeline_id") != pipeline_id
            or type(value.get("note_id")) is not int
            or value["note_id"] <= 0):
        raise StatusError("STATUS_FILE_MISMATCH")
    return value["note_id"]


def remove_status_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        raise StatusError("STATUS_FILE_CLEANUP_FAILED") from None


def publish(client: GitLabClient, state: str, project_id: int, iid: int, sha: str,
            pipeline_id: int, pipeline_url: str, status_path: Path,
            marker_name: str = common.DEFAULTS["comment_marker"]) -> str:
    mr = client.merge_request(iid)
    stale = mr["sha"] != sha or mr["state"] != "opened"
    actual_state = "canceled" if stale else state
    body = format_comment(
        actual_state, project_id, iid, sha, pipeline_id, pipeline_url, stale, marker_name)
    if state == "running":
        remove_status_file(status_path)
        note_id = client.create_note(iid, body)
        write_private_status(status_path, {
            "iid": iid, "sha": sha, "pipeline_id": pipeline_id, "note_id": note_id,
        })
    else:
        note_id = load_private_status(status_path, iid, sha, pipeline_id)
        client.update_note(iid, note_id, body)
        remove_status_file(status_path)
    return actual_state


def main(arguments: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if arguments is None else arguments
    try:
        if len(arguments) != 1 or arguments[0] not in ALLOWED_STATES:
            raise StatusError("INVALID_STATUS")
        policy = common.load_policy(POLICY_PATH)
        if not trusted_context(os.environ, policy):
            raise StatusError("REJECTED_CI_CONTEXT")
        server = common.load_server_config(common.server_config_path(policy))
        token = os.environ.get("GITLAB_REVIEW_TOKEN", "")
        if not token or any(character.isspace() for character in token):
            raise StatusError("MISSING_OR_INVALID_TOKEN")
        project_id = positive_int(os.environ.get("CI_PROJECT_ID", ""), "INVALID_PROJECT_ID")
        iid = positive_int(os.environ.get("REVIEW_MR_IID", ""), "INVALID_MR_IID")
        pipeline_id = positive_int(
            os.environ.get("CI_PIPELINE_ID", ""), "INVALID_PIPELINE_ID")
        sha = os.environ.get("REVIEW_MR_SHA", "")
        if not SHA_PATTERN.fullmatch(sha):
            raise StatusError("INVALID_MR_SHA")
        pipeline_url = validate_pipeline_url(
            os.environ.get("CI_PROJECT_URL", ""),
            os.environ.get("CI_PIPELINE_URL", ""), pipeline_id)
        client = GitLabClient(common.gitlab_api_base(os.environ, server), project_id, token,
                              target_branch=policy["target_branch"],
                              timeout=policy["timeouts"]["gitlab_seconds"])
        result = publish(
            client, arguments[0], project_id, iid, sha, pipeline_id, pipeline_url,
            common.workdir_path(server, "status.json"), policy["comment_marker"])
        print("REVIEW_STATUS: " + result.upper())
        return 0
    except StatusError as error:
        print("REVIEW_STATUS: " + error.code)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
