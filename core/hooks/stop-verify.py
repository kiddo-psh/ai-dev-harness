#!/usr/bin/env python3
"""Stop hook: 응답을 끝내기 전에 바뀐 영역의 검증 명령을 실행한다.

- 작업 트리에 변경이 없으면 아무것도 하지 않는다.
- 변경 파일이 속한 영역의 `areas[].verify`, 영역 밖 변경이면 `hooks.stop_verify`를 실행한다.
- 직전 확인과 변경 상태가 같으면 다시 실행하지 않는다. 그 상태가 실패였다면 보류하지 않고
  사용자에게 한 번 알린다(세션과 무관한 기존 변경 때문에 매 턴 보류되지 않게).
- 실패하면 한 번 종료를 보류하고(종료 코드 2) 결과를 모델에 넘긴다. 이미 보류한 뒤라면
  (`stop_hook_active`) 다시 보류하지 않고 사용자에게 경고만 남긴다.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True  # 대상 저장소의 .claude/hooks/에 __pycache__를 남기지 않는다
import harness_common as common  # noqa: E402

TAIL_LINES = 40
KILL_GRACE_SEC = 5


def notify(message: str) -> None:
    """종료를 막지 않고 사용자에게 보이는 알림."""
    print(json.dumps({"systemMessage": message}, ensure_ascii=False))


def changed_files(project: Path) -> tuple[list[str] | None, str]:
    """프로젝트 기준 변경 경로 목록과 오류. 프로젝트가 git 최상위의 하위 디렉터리여도 맞게 바꾼다."""
    top, error = common.git_result(project, "rev-parse", "--show-toplevel")
    if top is None:
        return None, error
    out, error = common.git_result(project, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if out is None:
        return None, error
    toplevel = Path(top.strip()).resolve()
    tokens = out.split("\0")
    raw, i = [], 0
    while i < len(tokens):
        token = tokens[i]
        i += 1
        if len(token) < 4:
            continue
        raw.append(token[3:])
        if token[0] in "RC" and i < len(tokens):  # 이름 변경은 다음 토큰이 원래 경로다
            raw.append(tokens[i])
            i += 1
    files = set()
    for path in raw:
        try:
            rel = (toplevel / path.rstrip("/")).relative_to(project).as_posix()
        except ValueError:
            continue  # 프로젝트 밖의 변경은 이 프로젝트의 검증 대상이 아니다
        if rel not in ("", "."):
            files.add(rel)
    return sorted(files), ""


def commands_for(config: dict, files: list[str]) -> list[str]:
    areas = sorted(config.get("areas", []), key=lambda a: len(a["dir"]), reverse=True)
    touched, root_touched = set(), False
    for path in files:
        owner = next((a["dir"] for a in areas if path == a["dir"] or path.startswith(a["dir"] + "/")), None)
        if owner is None:
            root_touched = True
        else:
            touched.add(owner)
    commands: list[str] = []
    for area in config.get("areas", []):  # 설정 순서대로 실행한다
        if area["dir"] in touched:
            commands.extend(c for c in area["verify"] if c not in commands)
    if root_touched:
        stop_verify = (config.get("hooks") or {}).get("stop_verify", [])
        commands.extend(c for c in stop_verify if c not in commands)
    return commands


def state_hash(project: Path, files: list[str], commands: list[str]) -> str:
    digest = hashlib.sha256()
    digest.update((common.git(project, "rev-parse", "HEAD") or "<no-head>").encode())
    for cmd in commands:
        digest.update(b"\0cmd\0" + cmd.encode("utf-8"))
    for rel in files:
        digest.update(b"\0file\0" + rel.encode("utf-8") + b"\0")
        path = project / rel
        try:
            if path.is_dir():  # 하위 모듈·중첩 저장소는 그 안의 파일 내용으로 대신한다
                digest.update((common.git(path, "rev-parse", "HEAD") or "<none>").encode("utf-8"))
                for sub in sorted(p for p in path.rglob("*") if p.is_file() and ".git" not in p.parts):
                    digest.update(sub.relative_to(path).as_posix().encode("utf-8") + b"\0" + sub.read_bytes())
            elif path.is_file():
                digest.update(path.read_bytes())
            else:
                digest.update(b"<deleted>")
        except OSError:
            digest.update(b"<unreadable>")
    return digest.hexdigest()


def kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()


def run(cmd: str, cwd: Path, timeout: float) -> tuple[int | None, str]:
    """(종료 코드, 출력). 시간 초과면 종료 코드 None.

    출력은 파이프 대신 임시 파일로 받는다. 명령이 남긴 후손 프로세스가 파이프를 쥐고 있어도
    셸이 끝나면 바로 돌아오고, 시간 초과를 넘겨 기다리지 않는다.
    """
    kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" \
        else {"start_new_session": True}
    with tempfile.TemporaryFile() as out:
        proc = subprocess.Popen(cmd, shell=True, cwd=cwd, stdin=subprocess.DEVNULL,
                                stdout=out, stderr=subprocess.STDOUT, **kwargs)
        try:
            code = proc.wait(timeout=max(timeout, 0.1))
        except subprocess.TimeoutExpired:
            kill_tree(proc)
            try:
                proc.wait(timeout=KILL_GRACE_SEC)
            except subprocess.TimeoutExpired:
                pass
            code = None
        out.seek(0)
        return code, common.decode_output(out.read())


def tail(text: str) -> str:
    lines = text.rstrip().splitlines()
    shown = lines[-TAIL_LINES:]
    head = [f"... (앞 {len(lines) - len(shown)}줄 생략)"] if len(lines) > len(shown) else []
    return "\n".join(head + shown)


def read_cache(path: Path | None) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path else {}
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_cache(path: Path | None, data: dict) -> None:
    try:
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def main() -> int:
    common.setup_streams()
    try:
        payload = common.read_payload()
    except ValueError as exc:
        print(f"harness stop-verify: 입력을 읽지 못해 종료 검증을 건너뛴다: {exc}", file=sys.stderr)
        return 1
    project = common.project_dir(payload)
    try:
        config = common.load_config(project)
    except common.ConfigError as exc:
        print(f"harness stop-verify: {common.CONFIG_NAME}를 읽지 못해 종료 검증이 꺼진 상태다: {exc}",
              file=sys.stderr)
        return 1
    files, error = changed_files(project)
    if files is None:
        notify(f"harness stop-verify: git 상태를 읽지 못해 종료 검증을 건너뛴다: {error}")
        return 0
    commands = commands_for(config, files)
    if not commands:
        return 0

    cache_path = common.git_state_path(project, "stop-verify.json")
    cache = read_cache(cache_path)
    current = state_hash(project, files, commands)
    if cache.get("state") == current:
        if not cache.get("ok") and not cache.get("notified"):
            notify("harness stop-verify: 직전 확인과 같은 상태에서 검증이 실패한 채다. "
                   "다시 보류하지 않는다. 사람이 확인한다.\n\n" + str(cache.get("report", "")))
            write_cache(cache_path, {**cache, "notified": True})
        return 0

    per_command = (config.get("hooks") or {}).get("stop_timeout_sec", common.DEFAULT_STOP_TIMEOUT)
    deadline = time.monotonic() + common.MAX_STOP_TIMEOUT  # settings.json의 hook timeout 안에서 끝낸다
    failures = []
    for cmd in commands:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            failures.append((cmd, None, "(전체 시간 예산을 넘어 실행하지 않았다)"))
            continue
        code, output = run(cmd, project, min(per_command, remaining))
        if code != 0:
            failures.append((cmd, code, output))

    if not failures:
        write_cache(cache_path, {"state": current, "ok": True})
        return 0

    active = bool(payload.get("stop_hook_active"))
    common.log_event(project, {
        "hook": "stop-verify", "decision": "fail", "commands": [cmd for cmd, _, _ in failures],
        "retry": active, "session": payload.get("session_id"),
    })
    report = []
    for cmd, code, output in failures:
        status = "시간 초과" if code is None else f"종료 코드 {code}"
        report.append(f"$ {cmd}  ({status})\n{tail(output)}")
    body = "\n\n".join(report)
    write_cache(cache_path, {"state": current, "ok": False, "notified": active, "report": body})
    if active:
        notify("harness stop-verify: 검증이 여전히 실패한다. 다시 보류하지 않고 종료한다. "
               "사람이 확인한다.\n\n" + body)
        return 0
    print("세션 종료 전 검증이 실패했다. 원인을 고친 뒤 다시 끝낸다. "
          "고칠 수 없으면 이유를 사용자에게 보고한다.\n\n" + body, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
