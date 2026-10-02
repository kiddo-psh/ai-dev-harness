#!/usr/bin/env python3
"""Claude MR 리뷰 스크립트의 공통 규칙. 표준 라이브러리만 사용한다.

저장소 정책은 `harness.json`의 `claude_review` 블록(보호 브랜치 체크아웃에서 읽는다), 서버 고유값은
`/etc/<review_name>/config.json`(root 소유)에서 읽는다. 키트의 `bin/harness.py`도 이 파일로
`claude_review` 블록을 검사하므로 `init`과 실행 시점의 규칙이 같다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat

# 도구 없는 실행. 도구·slash command·설정 파일·MCP·hook·세션 저장을 끈다. 테스트가 이 목록을 고정한다.
CLI_ARGS = (
    "-p", "--output-format", "json", "--max-turns", "1",
    "--tools", "", "--disable-slash-commands", "--setting-sources", "",
    "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
    "--settings", '{"disableAllHooks":true}', "--no-session-persistence",
)

# 자격 증명 종류별 환경 변수. 자식 프로세스에는 고른 하나만 넘긴다.
CREDENTIAL_VARIABLES = {"api_key": "ANTHROPIC_API_KEY", "oauth": "CLAUDE_CODE_OAUTH_TOKEN"}

POLICY_KEYS = {"target_branch", "environment", "review_name", "credential", "comment_marker",
               "rules_docs", "limits", "timeouts"}
RULES_DOC_KEYS = {"path", "when_changed"}
DEFAULT_RULES_DOCS = [{"path": "AGENTS.md"}, {"path": "CLAUDE.md"}]
# 크기 상한은 낮추기만 할 수 있다. 응답·입력 파일 상한(MAX_RESPONSE_BYTES 등)이 이 값을 전제로 한다.
DEFAULT_LIMITS = {
    "max_files": 100,
    "max_file_diff_bytes": 128 * 1024,
    "max_total_diff_bytes": 512 * 1024,
    "max_title_bytes": 1024,
    "max_description_bytes": 16 * 1024,
    "max_guidance_bytes": 256 * 1024,
    "max_context_files": 24,
    "max_context_file_bytes": 48 * 1024,
    "max_repository_context_bytes": 192 * 1024,
}
# 시간 제한(초)과 상한. 상한은 조각의 job 제한(주 실행 8분, 인증 검사 5분) 안에 들어가게 정했다.
DEFAULT_TIMEOUTS = {"claude_seconds": 240, "auth_check_seconds": 120, "gitlab_seconds": 20}
TIMEOUT_CEILINGS = {"claude_seconds": 300, "auth_check_seconds": 240, "gitlab_seconds": 60}
DEFAULTS = {"environment": "claude-review", "review_name": "claude-review", "credential": "api_key",
            "comment_marker": "harness-claude-review"}

SERVER_KEYS = {"claude_cli", "claude_version", "workdir", "account", "uid", "home", "nft_table",
               "deny_ips", "dns_ips", "gitlab_host"}
SERVER_CONFIG_DIR = Path("/etc")

NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
MARKER_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ACCOUNT_PATTERN = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
TABLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
HOST_PATTERN = re.compile(r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
MAX_POLICY_FILE_BYTES = 256 * 1024
MAX_SERVER_CONFIG_BYTES = 64 * 1024


class PolicyError(ValueError):
    """설정이 계약과 다르다. 메시지에는 설정 키만 넣고 값은 넣지 않는다."""


class ReviewError(RuntimeError):
    """분류 코드만 출력할 수 있는 실행 실패."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _safe_relative(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/"):
        return False
    if re.match(r"^[A-Za-z]:", value) or any(char.isspace() for char in value):
        return False
    return all(part not in ("", ".", "..") for part in value.split("/"))


def _non_empty_token(value: object) -> bool:
    return isinstance(value, str) and bool(value) and not any(char.isspace() for char in value)


def _int_in_range(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def validate_policy(block: object, source: str = "claude_review") -> dict:
    """`claude_review` 블록을 검사하고 기본값을 채운 정책을 돌려준다."""
    if not isinstance(block, dict):
        raise PolicyError(f"{source}: claude_review는 객체여야 한다")
    unknown = sorted(set(block) - POLICY_KEYS)
    if unknown:
        raise PolicyError(f"{source}: claude_review에 알 수 없는 키가 있다: {', '.join(unknown)}")
    if not _non_empty_token(block.get("target_branch")):
        raise PolicyError(f"{source}: claude_review.target_branch는 공백 없는 비어 있지 않은 문자열이어야 한다")
    policy = {"target_branch": block["target_branch"]}
    for key in ("environment", "review_name", "comment_marker", "credential"):
        value = block.get(key, DEFAULTS[key])
        if not isinstance(value, str):
            raise PolicyError(f"{source}: claude_review.{key}는 문자열이어야 한다")
        policy[key] = value
    if not _non_empty_token(policy["environment"]):
        raise PolicyError(f"{source}: claude_review.environment는 공백 없는 비어 있지 않은 문자열이어야 한다")
    if not NAME_PATTERN.fullmatch(policy["review_name"]) or len(policy["review_name"]) > 64:
        raise PolicyError(f"{source}: claude_review.review_name은 소문자·숫자와 . _ - 로 된 이름이어야 한다")
    if not MARKER_PATTERN.fullmatch(policy["comment_marker"]) or len(policy["comment_marker"]) > 64:
        raise PolicyError(f"{source}: claude_review.comment_marker는 소문자·숫자와 - 로 된 이름이어야 한다")
    if policy["credential"] not in CREDENTIAL_VARIABLES:
        raise PolicyError(f"{source}: claude_review.credential은 {sorted(CREDENTIAL_VARIABLES)} 중 하나여야 한다")
    policy["rules_docs"] = _validate_rules_docs(block.get("rules_docs", DEFAULT_RULES_DOCS), source)
    policy["limits"] = _validate_numbers(block.get("limits", {}), DEFAULT_LIMITS, DEFAULT_LIMITS,
                                         "limits", source)
    policy["timeouts"] = _validate_numbers(block.get("timeouts", {}), DEFAULT_TIMEOUTS, TIMEOUT_CEILINGS,
                                           "timeouts", source)
    return policy


def _validate_rules_docs(docs: object, source: str) -> list[dict]:
    if not isinstance(docs, list) or not docs:
        raise PolicyError(f"{source}: claude_review.rules_docs는 비어 있지 않은 목록이어야 한다")
    result, seen = [], set()
    for doc in docs:
        if not isinstance(doc, dict) or "path" not in doc or set(doc) - RULES_DOC_KEYS:
            raise PolicyError(f"{source}: claude_review.rules_docs 항목은 path와 선택 when_changed만 가진다")
        if not _safe_relative(doc["path"]):
            raise PolicyError(f"{source}: claude_review.rules_docs path는 저장소 안의 상대 경로여야 한다")
        if doc["path"] in seen:
            raise PolicyError(f"{source}: claude_review.rules_docs path가 중복된다")
        seen.add(doc["path"])
        entry = {"path": doc["path"]}
        if "when_changed" in doc:
            prefixes = doc["when_changed"]
            if not isinstance(prefixes, list) or not prefixes or any(
                    not _safe_relative(prefix.rstrip("/")) if isinstance(prefix, str) else True
                    for prefix in prefixes):
                raise PolicyError(f"{source}: claude_review.rules_docs when_changed는 상대 경로 접두사 목록이어야 한다")
            entry["when_changed"] = list(prefixes)
        result.append(entry)
    return result


def _validate_numbers(values: object, defaults: dict, ceilings: dict, name: str, source: str) -> dict:
    if not isinstance(values, dict):
        raise PolicyError(f"{source}: claude_review.{name}는 객체여야 한다")
    unknown = sorted(set(values) - set(defaults))
    if unknown:
        raise PolicyError(f"{source}: claude_review.{name}에 알 수 없는 키가 있다: {', '.join(unknown)}")
    result = dict(defaults)
    for key, value in values.items():
        if not _int_in_range(value, 1, ceilings[key]):
            raise PolicyError(f"{source}: claude_review.{name}.{key}는 1 이상 {ceilings[key]} 이하 정수여야 한다")
        result[key] = value
    return result


def load_policy(path: Path) -> dict:
    """보호 브랜치 체크아웃의 harness.json에서 claude_review 정책을 읽는다."""
    try:
        details = path.lstat()
        if not stat.S_ISREG(details.st_mode) or details.st_size > MAX_POLICY_FILE_BYTES:
            raise ReviewError("INVALID_REVIEW_POLICY")
        config = json.loads(path.read_text(encoding="utf-8"))
    except ReviewError:
        raise
    except (OSError, UnicodeError, ValueError):
        raise ReviewError("INVALID_REVIEW_POLICY") from None
    if not isinstance(config, dict) or "claude_review" not in config:
        raise ReviewError("INVALID_REVIEW_POLICY")
    try:
        return validate_policy(config["claude_review"])
    except PolicyError:
        raise ReviewError("INVALID_REVIEW_POLICY") from None


def server_config_path(policy: dict) -> Path:
    return SERVER_CONFIG_DIR / policy["review_name"] / "config.json"


def _require_root_owned(path: Path, regular: bool) -> None:
    details = path.lstat()
    expected = stat.S_ISREG(details.st_mode) if regular else stat.S_ISDIR(details.st_mode)
    if not expected:
        raise ReviewError("UNSAFE_SERVER_CONFIG")
    if os.name != "nt" and (details.st_uid != 0 or details.st_mode & 0o022):
        raise ReviewError("UNSAFE_SERVER_CONFIG")


def validate_server_config(config: object) -> dict:
    if not isinstance(config, dict) or set(config) != SERVER_KEYS:
        raise ReviewError("INVALID_SERVER_CONFIG")
    for key in ("claude_cli", "workdir", "home"):
        value = config[key]
        if (not isinstance(value, str) or not value.startswith("/") or "\\" in value
                or any(part in (".", "..") for part in value.split("/"))
                or any(char.isspace() for char in value)):
            raise ReviewError("INVALID_SERVER_CONFIG")
    if (not isinstance(config["account"], str) or not ACCOUNT_PATTERN.fullmatch(config["account"])
            or not _int_in_range(config["uid"], 1, 4294967294)
            or not isinstance(config["nft_table"], str) or not TABLE_PATTERN.fullmatch(config["nft_table"])
            or not isinstance(config["gitlab_host"], str) or not HOST_PATTERN.fullmatch(config["gitlab_host"])
            or not isinstance(config["claude_version"], str)
            or not VERSION_PATTERN.fullmatch(config["claude_version"])):
        raise ReviewError("INVALID_SERVER_CONFIG")
    for key in ("deny_ips", "dns_ips"):  # 주소 자체의 검사는 network-guard가 한다
        if not isinstance(config[key], list) or not all(isinstance(item, str) for item in config[key]):
            raise ReviewError("INVALID_SERVER_CONFIG")
    return config


def load_server_config(path: Path) -> dict:
    """root 소유이고 그룹·기타 사용자가 쓸 수 없는 서버 설정만 읽는다."""
    try:
        for parent in reversed(path.parents):
            _require_root_owned(parent, regular=False)
        _require_root_owned(path, regular=True)
        if path.lstat().st_size > MAX_SERVER_CONFIG_BYTES:
            raise ReviewError("INVALID_SERVER_CONFIG")
        config = json.loads(path.read_text(encoding="utf-8"))
    except ReviewError:
        raise
    except OSError:
        raise ReviewError("SERVER_CONFIG_UNAVAILABLE") from None
    except (UnicodeError, ValueError):
        raise ReviewError("INVALID_SERVER_CONFIG") from None
    return validate_server_config(config)


def trusted_context(env, policy: dict, allow_api_trigger: bool = True) -> bool:
    """보호 대상 브랜치의 push·web(선택: 표식 있는 api) 파이프라인만. MR 파이프라인과 debug trace는 거부한다."""
    source = env.get("CI_PIPELINE_SOURCE")
    allowed_source = (source in ("push", "web")
                      or (allow_api_trigger and source == "api"
                          and env.get("CLAUDE_REVIEW_TRIGGER") == "comment"))
    return (env.get("CI_COMMIT_BRANCH") == policy["target_branch"]
            and env.get("CI_COMMIT_REF_PROTECTED") == "true"
            and env.get("CI_ENVIRONMENT_NAME") == policy["environment"]
            and allowed_source
            and env.get("CI_DEBUG_TRACE", "").lower() not in ("true", "1")
            and env.get("CI_DEBUG_SERVICES", "").lower() not in ("true", "1"))


def read_credential(env, policy: dict) -> tuple[str, str]:
    """정책이 고른 자격 증명 하나만 읽는다. 다른 종류의 변수는 보지 않는다."""
    name = CREDENTIAL_VARIABLES[policy["credential"]]
    value = env.get(name, "")
    if not _non_empty_token(value):
        raise ReviewError("MISSING_OR_INVALID_TOKEN")
    return name, value


def child_environment(credential_name: str, token: str, home: Path) -> dict[str, str]:
    """Claude CLI 자식 프로세스 환경. GitLab 토큰, 다른 자격 증명, proxy와 프로젝트 환경은 넣지 않는다."""
    if credential_name not in CREDENTIAL_VARIABLES.values():
        raise ReviewError("INVALID_CREDENTIAL")
    return {"HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
            "PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
            credential_name: token, "DISABLE_AUTOUPDATER": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}


def workdir_path(server: dict, name: str) -> Path:
    return Path(server["workdir"]) / name


def changed_matches(path: str, prefixes: list[str]) -> bool:
    return any(path.startswith(prefix) for prefix in prefixes)
