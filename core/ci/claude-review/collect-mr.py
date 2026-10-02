#!/usr/bin/env python3
"""GitLab API에서 실행하지 않을 MR 메타데이터와 diff만 제한적으로 수집한다."""

from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path
import re
import stat
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
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
MAX_FILES = common.DEFAULT_LIMITS["max_files"]
MAX_FILE_DIFF_BYTES = common.DEFAULT_LIMITS["max_file_diff_bytes"]
MAX_TOTAL_DIFF_BYTES = common.DEFAULT_LIMITS["max_total_diff_bytes"]
MAX_TITLE_BYTES = common.DEFAULT_LIMITS["max_title_bytes"]
MAX_DESCRIPTION_BYTES = common.DEFAULT_LIMITS["max_description_bytes"]
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


CollectionError = common.ReviewError


class GitLabClient:
    def __init__(self, api_url: str, project_id: int, token: str, opener=urlopen,
                 target_branch: str = "", limits: dict | None = None, timeout: int = 20):
        if not api_url.startswith("https://"):
            raise CollectionError("INVALID_API_URL")
        self.api_url = api_url.rstrip("/")
        self.project_id = project_id
        self.token = token
        self.opener = opener
        self.target_branch = target_branch
        self.limits = dict(common.DEFAULT_LIMITS, **(limits or {}))
        self.timeout = timeout

    def get(self, path: str, query: dict[str, object] | None = None):
        url = self.api_url + path
        if query:
            url += "?" + urlencode(query)
        request = Request(url, headers={"PRIVATE-TOKEN": self.token, "Accept": "application/json"})
        try:
            with self.opener(request, timeout=self.timeout) as response:
                length = response.headers.get("Content-Length")
                if length and int(length) > MAX_RESPONSE_BYTES:
                    raise CollectionError("GITLAB_RESPONSE_TOO_LARGE")
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise CollectionError("GITLAB_RESPONSE_TOO_LARGE")
                return json.loads(body), response.headers
        except CollectionError:
            raise
        except HTTPError as error:
            if error.code in (401, 403):
                raise CollectionError("GITLAB_AUTHENTICATION_FAILED") from None
            if error.code == 404:
                raise CollectionError("MR_NOT_FOUND") from None
            if error.code == 429:
                raise CollectionError("GITLAB_RATE_LIMITED") from None
            raise CollectionError("GITLAB_API_FAILED") from None
        except (URLError, TimeoutError):
            raise CollectionError("GITLAB_CONNECTION_FAILED") from None
        except (ValueError, TypeError, json.JSONDecodeError):
            raise CollectionError("INVALID_GITLAB_RESPONSE") from None

    def collect(self, iid: int, expected_sha: str) -> dict[str, object]:
        project = quote(str(self.project_id), safe="")
        mr_path = f"/projects/{project}/merge_requests/{iid}"
        metadata, _ = self.get(mr_path)
        validate_metadata(metadata, self.project_id, iid, expected_sha, self.target_branch)

        # `/changes`를 `access_raw_diffs`와 함께 부른다.
        #
        # **`/diffs`로는 큰 파일을 받을 수 없다.** GitLab은 한 파일의 패치가 약 10KB를 넘으면
        # `collapsed: true`에 빈 `diff`로 내려주고, `/diffs`에는 그것을 펼 인자가 없다.
        # `build_review_input`이 접힌 파일을 거절하므로 파일 하나만 커도 MR 전체가
        # `INCOMPLETE_DIFF_REJECTED`가 됐다. lock 파일이 늘 걸리던 것도 같은 이유다.
        #
        # 원본 운영에서 16KB짜리 파일 하나가 있는 MR로 확인했다. `/diffs`,
        # `/diffs?access_raw_diffs=true`, `/diffs?unidiff=true`는 모두 접힌 채로 왔고,
        # `/changes?access_raw_diffs=true`만 전문을 내려줬다.
        #
        # `/changes`는 GitLab 15.7에서 deprecated로 표시됐지만 대체재인 `/diffs`가 이 인자를
        # 받지 않아 아직 유일한 경로다. `/diffs`가 받게 되면 그쪽으로 옮긴다.
        #
        # 페이지가 나뉘지 않는다. 한 번에 다 오므로 응답 자체가 `MAX_RESPONSE_BYTES`에 걸릴 수
        # 있는데, 그 2MB는 이 파일이 허용하는 총 diff 상한보다 커서 정상 MR은 닿지 않는다.
        payload, _ = self.get(mr_path + "/changes", {"access_raw_diffs": "true"})
        if not isinstance(payload, dict):
            raise CollectionError("INVALID_GITLAB_RESPONSE")
        changes = payload.get("changes")
        if not isinstance(changes, list):
            raise CollectionError("INVALID_GITLAB_RESPONSE")
        if len(changes) > self.limits["max_files"]:
            raise CollectionError("DIFF_FILE_LIMIT_EXCEEDED")

        return build_review_input(metadata, changes, self.limits)


def positive_int(value: str, code: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise CollectionError(code) from None
    if number <= 0:
        raise CollectionError(code)
    return number


def validate_metadata(metadata: object, project_id: int, iid: int, expected_sha: str,
                      target_branch: str) -> None:
    if not isinstance(metadata, dict):
        raise CollectionError("INVALID_GITLAB_RESPONSE")
    if metadata.get("iid") != iid or metadata.get("state") != "opened":
        raise CollectionError("MR_NOT_OPEN")
    if not target_branch or metadata.get("target_branch") != target_branch:
        raise CollectionError("TARGET_BRANCH_NOT_ALLOWED")
    if metadata.get("source_project_id") != project_id or metadata.get("target_project_id") != project_id:
        raise CollectionError("FORK_OR_DIFFERENT_PROJECT_REJECTED")
    actual_sha = metadata.get("sha")
    if not isinstance(actual_sha, str) or not SHA_PATTERN.fullmatch(actual_sha):
        raise CollectionError("INVALID_GITLAB_RESPONSE")
    if not SHA_PATTERN.fullmatch(expected_sha) or actual_sha != expected_sha:
        raise CollectionError("MR_SHA_MISMATCH")


def build_review_input(metadata: dict[str, object], changes: list[dict[str, object]],
                       limits: dict | None = None) -> dict[str, object]:
    limits = dict(common.DEFAULT_LIMITS, **(limits or {}))
    files = []
    total_bytes = 0
    for change in changes:
        if not isinstance(change, dict):
            raise CollectionError("INVALID_GITLAB_RESPONSE")
        # `collect`가 `access_raw_diffs`로 받으므로 `collapsed`는 이제 오지 않아야 한다.
        # 그래도 검사를 남긴다 — 인자가 먹지 않게 되면 빈 diff를 리뷰하는 대신 여기서 멈춘다.
        if change.get("too_large") or change.get("collapsed"):
            raise CollectionError("INCOMPLETE_DIFF_REJECTED")
        old_path, new_path, diff = change.get("old_path"), change.get("new_path"), change.get("diff")
        if not all(isinstance(value, str) for value in (old_path, new_path, diff)):
            raise CollectionError("INVALID_GITLAB_RESPONSE")
        size = len(diff.encode("utf-8"))
        if size > limits["max_file_diff_bytes"]:
            raise CollectionError("FILE_DIFF_LIMIT_EXCEEDED")
        total_bytes += size
        if total_bytes > limits["max_total_diff_bytes"]:
            raise CollectionError("TOTAL_DIFF_LIMIT_EXCEEDED")
        files.append({
            "old_path": old_path,
            "new_path": new_path,
            "new_file": change.get("new_file") is True,
            "renamed_file": change.get("renamed_file") is True,
            "deleted_file": change.get("deleted_file") is True,
            "generated_file": change.get("generated_file") is True,
            "diff": diff,
        })
    return {
        "untrusted_data": True,
        "merge_request": {
            "iid": metadata["iid"],
            "title": limited_text(metadata.get("title"), limits["max_title_bytes"]),
            "description": limited_text(metadata.get("description") or "", limits["max_description_bytes"]),
            "source_branch": limited_text(metadata.get("source_branch"), 1024),
            "target_branch": metadata["target_branch"],
            "sha": metadata["sha"],
        },
        "files": files,
        "limits": {"file_count": len(files), "total_diff_bytes": total_bytes},
    }


def limited_text(value: object, maximum_bytes: int) -> str:
    if not isinstance(value, str):
        raise CollectionError("INVALID_GITLAB_RESPONSE")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise CollectionError("MR_METADATA_LIMIT_EXCEEDED")
    return value


def trusted_context(env: dict[str, str], policy: dict) -> bool:
    return common.trusted_context(env, policy)


def write_private_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(payload, output, ensure_ascii=False, separators=(",", ":"))
        temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    try:
        policy = common.load_policy(POLICY_PATH)
        if not trusted_context(os.environ, policy):
            raise CollectionError("REJECTED_CI_CONTEXT")
        server = common.load_server_config(common.server_config_path(policy))
        token = os.environ.get("GITLAB_REVIEW_TOKEN", "")
        if not token or any(character.isspace() for character in token):
            raise CollectionError("MISSING_OR_INVALID_TOKEN")
        project_id = positive_int(os.environ.get("CI_PROJECT_ID", ""), "INVALID_PROJECT_ID")
        iid = positive_int(os.environ.get("REVIEW_MR_IID", ""), "INVALID_MR_IID")
        expected_sha = os.environ.get("REVIEW_MR_SHA", "")
        client = GitLabClient(os.environ.get("CI_API_V4_URL", ""), project_id, token,
                              target_branch=policy["target_branch"], limits=policy["limits"],
                              timeout=policy["timeouts"]["gitlab_seconds"])
        output_path = common.workdir_path(server, "input.json")
        # 이전 실행 결과가 실패한 새 실행의 입력으로 재사용되지 않게 먼저 제거한다.
        output_path.unlink(missing_ok=True)
        write_private_json(output_path, client.collect(iid, expected_sha))
        print("MR_COLLECTION: PASS")
        return 0
    except CollectionError as error:
        print("MR_COLLECTION: " + error.code)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
