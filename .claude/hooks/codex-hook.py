#!/usr/bin/env python3
"""Codex Stop·SessionEnd hook: 저장소 안 `telemetry push`를 백그라운드로 띄운다(#140).

Codex는 대화형 세션에서만 프로젝트 hook(`.codex/hooks.json`)을 실행하고, 실측에서 `SessionEnd`는 종료해도 오지 않는
경우가 있었다(2026-10-23, Codex 0.164). 그래서 매 응답 끝(`Stop`)을 주 계기로 쓰고 `SessionEnd`는 보조로 둔다.

    python .claude/hooks/codex-hook.py stop          # 마지막으로 띄운 뒤 THROTTLE_SEC가 지났을 때만 띄운다
    python .claude/hooks/codex-hook.py session-end   # 항상 띄운다

- 아무것도 출력하지 않고 무엇이 실패해도 종료 코드 0이다. 응답·종료를 막지 않는다.
- 주소·인증 판단은 Claude SessionEnd와 같다(`harness_common.spawn_telemetry_push`). 전송 위치·잠금은 push가 공유하므로
  여러 세션이 동시에 띄워도 중복 전송되지 않는다.
- 입력에서는 `cwd`만 읽는다. 마지막 응답 본문 등 다른 필드는 쓰지 않는다.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True  # 대상 저장소의 .claude/hooks/에 __pycache__를 남기지 않는다
import harness_common as common  # noqa: E402

THROTTLE_SEC = 300
MARK = "codex-push.last"  # worktree별 `.git/harness/`의 마지막 실행 표시(내용 없음, 수정 시각만 쓴다)


def project_of(payload: dict) -> Path | None:
    """hook 입력의 cwd(하위 디렉터리일 수 있다)가 속한 worktree 루트. git 저장소가 아니면 None."""
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) and payload.get("cwd") else os.getcwd()
    top = common.git(Path(cwd), "rev-parse", "--show-toplevel")
    return Path(top.strip()) if top and top.strip() else None


def due(mark: Path, now: float) -> bool:
    try:
        return now - mark.stat().st_mtime >= THROTTLE_SEC
    except OSError:
        return True  # 표시가 없다(첫 실행)


def run(event: str, payload: dict, now: float | None = None) -> bool:
    """push를 띄웠으면 True."""
    project = project_of(payload)
    if project is None:
        return False
    mark = common.git_state_path(project, MARK)
    now = time.time() if now is None else now
    if event == "stop" and mark is not None and not due(mark, now):
        return False
    if not common.spawn_telemetry_push(project):
        return False
    if mark is not None:
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.touch()
        os.utime(mark, (now, now))
    return True


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        payload = common.read_payload()
    except Exception:  # noqa: BLE001 - 입력이 깨져도 cwd 없이 진행한다
        payload = {}
    try:
        if argv and argv[0] in ("stop", "session-end"):
            run(argv[0], payload)
    except Exception:  # noqa: BLE001 - 전송을 띄우지 못해도 Codex 응답·종료에 영향이 없다
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
