"""hooks 공통 코드. 대상 저장소의 `.claude/hooks/`에 복사되며 표준 라이브러리만 쓴다.

키트의 `bin/harness.py`도 이 파일을 읽어 `harness.json`의 `hooks` 항목을 같은 규칙으로 검사한다.
"""

from __future__ import annotations

import datetime
import json
import locale
import os
import re
import subprocess
import sys
from pathlib import Path

CONFIG_NAME = "harness.json"
HOOK_KEYS = {"protected_paths", "stop_verify", "stop_timeout_sec", "python"}
RULE_KEYS = {"pattern", "mode", "reason"}
MODES = ("ask", "block")  # 뒤로 갈수록 강하다
DEFAULT_PYTHON = "python3"
DEFAULT_STOP_TIMEOUT = 300
MAX_STOP_TIMEOUT = 840  # settings.json의 Stop hook timeout(900초)보다 작아야 한다

# 설정과 무관하게 항상 적용한다. AI가 hook이나 설정을 고쳐 스스로 가드레일을 푸는 경로를 막는다.
ALWAYS_PROTECTED = [
    {"pattern": "/.claude/settings.json", "mode": "block", "reason": "hooks 설정(자기 보호)"},
    {"pattern": "/.claude/settings.local.json", "mode": "block", "reason": "hooks 설정(자기 보호)"},
    {"pattern": "/.claude/hooks/", "mode": "block", "reason": "hooks 스크립트(자기 보호)"},
    {"pattern": "/harness.json", "mode": "ask", "reason": "키트 설정(보호 규칙·종료 검증)"},
]

# 프로젝트 밖이지만 hooks를 끌 수 있는 사용자 설정. 전역 설정을 맡기는 정상 작업이 있어 확인만 받는다.
USER_SETTINGS = ("settings.json", "settings.local.json")

# `harness.json`의 hooks.protected_paths가 없을 때 쓰는 기본값. 지정하면 이 목록을 대체한다.
DEFAULT_PROTECTED = [
    *({"pattern": name, "mode": "block", "reason": "lock 파일(패키지 관리자가 생성)"} for name in (
        "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "gradle.lockfile",
        "poetry.lock", "uv.lock", "Cargo.lock", "go.sum",
    )),
    {"pattern": ".gitlab-ci.yml", "mode": "ask", "reason": "CI 정의"},
    {"pattern": "/.github/workflows/", "mode": "ask", "reason": "CI 정의"},
    {"pattern": "**/db/migration/", "mode": "ask", "reason": "DB 마이그레이션"},
    {"pattern": "migrations/", "mode": "ask", "reason": "DB 마이그레이션"},
    {"pattern": ".env.example", "mode": "ask", "reason": "환경 변수 계약"},
]


class ConfigError(Exception):
    """harness.json을 읽거나 검사하지 못했다."""


def _nonempty_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _str_list(value, allow_empty=False) -> bool:
    return isinstance(value, list) and (allow_empty or bool(value)) and all(_nonempty_str(v) for v in value)


def validate_hooks(hooks, source) -> None:
    if hooks is None:
        return
    if not isinstance(hooks, dict):
        raise ConfigError(f"{source}: hooks는 객체여야 한다")
    unknown = sorted(set(hooks) - HOOK_KEYS)
    if unknown:
        raise ConfigError(f"{source}: hooks에 알 수 없는 키가 있다: {', '.join(unknown)}")
    rules = hooks.get("protected_paths", [])
    if not isinstance(rules, list):
        raise ConfigError(f"{source}: hooks.protected_paths는 목록이어야 한다")
    for rule in rules:
        if not isinstance(rule, dict) or not _nonempty_str(rule.get("pattern")):
            raise ConfigError(f"{source}: hooks.protected_paths 항목에는 pattern이 필요하다")
        extra = sorted(set(rule) - RULE_KEYS)
        if extra:
            raise ConfigError(f"{source}: 보호 경로 {rule['pattern']}에 알 수 없는 키가 있다: {', '.join(extra)}")
        if rule.get("mode") not in MODES:
            raise ConfigError(f"{source}: 보호 경로 {rule['pattern']}의 mode는 {' 또는 '.join(MODES)}여야 한다")
        if "reason" in rule and not _nonempty_str(rule["reason"]):
            raise ConfigError(f"{source}: 보호 경로 {rule['pattern']}의 reason은 비어 있지 않은 문자열이어야 한다")
    if "stop_verify" in hooks and not _str_list(hooks["stop_verify"]):
        raise ConfigError(f"{source}: hooks.stop_verify는 비어 있지 않은 문자열 목록이어야 한다")
    if "stop_timeout_sec" in hooks:
        value = hooks["stop_timeout_sec"]
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_STOP_TIMEOUT:
            raise ConfigError(f"{source}: hooks.stop_timeout_sec는 1~{MAX_STOP_TIMEOUT} 정수여야 한다")
    if "python" in hooks:
        value = hooks["python"]
        # settings.json의 JSON 문자열 안에 그대로 들어가므로 따옴표·역슬래시·제어 문자를 받지 않는다
        if not _nonempty_str(value) or any(ch in '"\\' or ord(ch) < 0x20 for ch in value):
            raise ConfigError(f"{source}: hooks.python은 따옴표·역슬래시·제어 문자 없는 명령 이름이어야 한다")


def _normalized_dir(value) -> bool:
    if not _nonempty_str(value) or "\\" in value or value.startswith("/") or value.endswith("/"):
        return False
    return all(part not in ("", ".", "..") for part in value.split("/"))


def validate_areas_for_hooks(areas, source) -> None:
    """hook이 쓰는 영역 필드만 검사한다. 전체 검사는 키트의 `harness check`가 한다."""
    if not isinstance(areas, list):
        raise ConfigError(f"{source}: areas는 목록이어야 한다")
    for area in areas:
        if not isinstance(area, dict) or not _normalized_dir(area.get("dir")):
            raise ConfigError(f"{source}: areas 항목의 dir은 정규화된 상대 경로여야 한다")
        if not _str_list(area.get("verify")):
            raise ConfigError(f"{source}: 영역 {area['dir']}의 verify는 비어 있지 않은 문자열 목록이어야 한다")
        if "docs" in area and not _str_list(area["docs"]):
            raise ConfigError(f"{source}: 영역 {area['dir']}의 docs는 비어 있지 않은 문자열 목록이어야 한다")


def load_config(project: Path) -> dict:
    """대상의 harness.json. 없으면 빈 설정(기본값 적용)."""
    path = project / CONFIG_NAME
    if not path.is_file():
        return {}
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    if not isinstance(config, dict):
        raise ConfigError(f"{path}: 최상위는 객체여야 한다")
    validate_hooks(config.get("hooks"), path)
    validate_areas_for_hooks(config.get("areas", []), path)
    return config


# ---------------------------------------------------------------------------
# 경로
# ---------------------------------------------------------------------------


def compile_glob(pattern: str) -> re.Pattern:
    """gitignore 방식의 glob. 대소문자는 구분하지 않는다(대소문자 무시 FS에서의 우회 방지).

    - 앞의 `./`는 무시한다. 끝의 `/`는 "그 아래 전체"다.
    - `/`로 시작하거나 중간에 `/`가 있으면 루트 기준, 아니면 모든 깊이에서 맞춘다.
    - 패턴이 디렉터리에 맞으면 그 아래 파일도 맞는다.
    - `**`는 0개 이상의 디렉터리, `*`·`?`는 `/`를 넘지 않는다.
    """
    p = pattern.strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    dir_only = p.endswith("/")
    p = p.rstrip("/")
    if p.startswith("/"):
        p = p.lstrip("/")
    elif "/" not in p:
        p = "**/" + p
    parts = p.split("/")
    rx = ""
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if part == "**":
            rx += ".+" if last else "(?:[^/]+/)*"
            continue
        for ch in part:
            rx += "[^/]*" if ch == "*" else "[^/]" if ch == "?" else re.escape(ch)
        if not last:
            rx += "/"
    if parts[-1] != "**":
        rx += "/.+" if dir_only else "(?:/.+)?"
    return re.compile(rx, re.IGNORECASE)


def project_root_raw(payload: dict) -> str:
    return os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()


def project_dir(payload: dict) -> Path:
    return Path(project_root_raw(payload)).resolve()


def lexical(path: Path) -> Path:
    """링크를 따라가지 않고 `.`·`..`만 정리한 절대 경로."""
    return Path(os.path.normpath(os.path.abspath(path)))


def classify_path(project: Path, raw: str, cwd: str | None = None,
                  project_lexical: Path | None = None) -> tuple[str, list[str], list[Path], list[Path]]:
    """("unc", [], [], []) 또는 ("paths", 프로젝트 안 `a/b` 목록, 프로젝트 밖 절대 경로 목록, 판정한 절대 경로).

    링크를 따라가지 않은 논리 경로와 `resolve()`한 실제 경로를 둘 다 돌려준다. 보호 대상 이름이
    심볼릭 링크이거나, 링크된 디렉터리를 거쳐 보호 파일에 닿는 경우를 모두 잡기 위해서다.
    Windows의 `\\\\?\\` 확장 경로는 일반 경로로 바꾼다. 그 밖의 UNC 경로는 프로젝트 소속을
    확인할 수 없으므로 "unc"로 돌려 호출자가 확인을 받게 한다.
    """
    text = raw.replace("\\", "/")
    if os.name == "nt":
        if text.lower().startswith("//?/unc/"):
            text = "//" + text[8:]
        elif text.startswith("//?/") or text.startswith("//./"):
            text = text[4:]
        if text.startswith("//"):
            return "unc", [], [], []
    path = Path(text)
    if not path.is_absolute():
        path = Path(cwd or project) / path
    roots = [project] + ([project_lexical] if project_lexical and project_lexical != project else [])
    inside: list[str] = []
    outside: list[Path] = []
    candidates = [lexical(path), path.resolve()]
    for candidate in candidates:
        rel = None
        for root in roots:
            try:
                rel = candidate.relative_to(root).as_posix()
                break
            except ValueError:
                continue
        if rel is None:
            if candidate not in outside:
                outside.append(candidate)
        elif rel not in ("", ".") and rel not in inside:
            inside.append(rel)
    return "paths", inside, outside, candidates


def self_protected_real(project: Path, candidates: list[Path]) -> dict | None:
    """자기 보호 경로의 실제 위치와 비교한다. `.claude`나 `.claude/hooks`가 링크여도 그 대상 경로로 쓰거나
    다른 링크를 거쳐 쓰는 경우, 보호 파일의 하드링크를 다른 이름으로 쓰는 경우를 잡는다."""
    claude = project / ".claude"
    files = [claude / "settings.json", claude / "settings.local.json"]
    hooks = claude / "hooks"
    try:
        real_files = [f.resolve() for f in files]
        real_hooks = hooks.resolve()
        hook_files = [p for p in hooks.iterdir() if p.is_file()] if hooks.is_dir() else []
    except OSError:
        return None
    for candidate in candidates:
        try:
            real = candidate.resolve()
        except OSError:
            continue
        if real in real_files or real == real_hooks or real_hooks in real.parents:
            return {"pattern": "/.claude/(실제 위치)", "mode": "block", "reason": "hooks 설정·스크립트(자기 보호)"}
        if real.is_file():
            for protected in [*files, *hook_files]:
                try:
                    if protected.is_file() and os.path.samefile(real, protected):
                        return {"pattern": "/.claude/(같은 파일)", "mode": "block",
                                "reason": "hooks 설정·스크립트의 하드링크(자기 보호)"}
                except OSError:
                    continue
    return None


def is_user_settings(path: Path) -> bool:
    folder = Path.home() / ".claude"
    try:
        return path.parent.resolve() == folder.resolve() and path.name.lower() in USER_SETTINGS
    except OSError:
        return False


# ---------------------------------------------------------------------------
# git과 기록
# ---------------------------------------------------------------------------


def git_result(project: Path, *args: str, timeout: float = 30) -> tuple[str | None, str]:
    """(stdout, 오류 첫 줄). 실패하면 stdout이 None."""
    try:
        result = subprocess.run(["git", *args], cwd=project, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    if result.returncode != 0:
        lines = result.stderr.decode("utf-8", errors="replace").strip().splitlines()
        return None, lines[0] if lines else f"git 종료 코드 {result.returncode}"
    return result.stdout.decode("utf-8", errors="replace"), ""


def git(project: Path, *args: str) -> str | None:
    return git_result(project, *args)[0]


def git_state_path(project: Path, name: str) -> Path | None:
    """worktree마다 따로 두는 git 내부 경로(`.git/harness/<name>`). git 저장소가 아니면 None."""
    out = git(project, "rev-parse", "--git-path", f"harness/{name}")
    if not out:
        return None
    path = Path(out.strip())
    return path if path.is_absolute() else project / path


def log_event(project: Path, record: dict) -> None:
    """판정 기록 한 줄. 실패해도 판정에 영향을 주지 않는다."""
    try:
        path = git_state_path(project, "events.jsonl")
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"ts": stamp, **record}, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - 기록은 최선 노력
        pass


def decode_output(data: bytes) -> str:
    """명령 출력. UTF-8이 아니면 시스템 로캘 인코딩(한국어 Windows의 cp949 등)으로 읽는다."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode(locale.getpreferredencoding(False) or "utf-8", errors="replace")


def read_payload() -> dict:
    data = sys.stdin.buffer.read().decode("utf-8-sig")  # BOM이 붙은 입력(PowerShell 파이프 등)도 읽는다
    payload = json.loads(data) if data.strip() else {}
    if not isinstance(payload, dict):
        raise ValueError("hook 입력은 JSON 객체여야 한다")
    return payload


def setup_streams() -> None:
    for stream in (sys.stdout, sys.stderr):  # Windows 콘솔에서도 한국어 메시지를 깨지지 않게 출력한다
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
