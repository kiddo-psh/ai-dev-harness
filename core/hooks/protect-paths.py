#!/usr/bin/env python3
"""PreToolUse hook: 보호 경로를 고치려는 파일 도구 호출을 거부(block)하거나 사용자 확인(ask)으로 돌린다.

규칙은 대상 저장소의 `harness.json` `hooks.protected_paths`(없으면 기본값)와 `areas[].docs`,
그리고 끌 수 없는 규칙(자기 보호, `harness.json`)이다. Bash 명령을 통한 쓰기는 보지 않는다
(README "알려진 우회"). 설정을 읽지 못하면 끌 수 없는 규칙만 적용하고 알린다(fail-open).
"""

from __future__ import annotations

import json
import sys

sys.dont_write_bytecode = True  # 대상 저장소의 .claude/hooks/에 __pycache__를 남기지 않는다
import harness_common as common  # noqa: E402

# 도구별로 대상 파일 경로가 들어 있는 입력 키
TOOL_PATH_KEYS = {"Edit": "file_path", "Write": "file_path", "MultiEdit": "file_path",
                  "NotebookEdit": "notebook_path"}

OFF_NOTICE = "보호 경로 검사가 끌 수 없는 규칙만 남기고 꺼진 상태다"


def rules_for(config: dict | None) -> list[dict]:
    if config is None:
        return list(common.ALWAYS_PROTECTED)
    hooks = config.get("hooks") or {}
    rules = hooks.get("protected_paths")
    if rules is None:
        rules = common.DEFAULT_PROTECTED
    docs = [
        {"pattern": "/" + doc_path(doc), "mode": "ask", "reason": "계약 문서"}
        for area in config.get("areas", []) for doc in area.get("docs", [])
    ]
    return [*common.ALWAYS_PROTECTED, *rules, *docs]


def doc_path(doc: str) -> str:
    """영역 기준 문서 경로를 루트 기준 패턴 본문으로. `./`·앞 `/`를 떼어 낸다."""
    path = doc.strip().replace("\\", "/")
    while path.startswith("./") or path.startswith("/"):
        path = path[2:] if path.startswith("./") else path[1:]
    return path


def decide(rel: str, rules: list[dict]) -> dict | None:
    """일치하는 규칙 중 가장 강한 것. 같은 강도면 먼저 나온 규칙."""
    best = None
    for rule in rules:
        if not common.compile_glob(rule["pattern"]).fullmatch(rel):
            continue
        if best is None or common.MODES.index(rule["mode"]) > common.MODES.index(best["mode"]):
            best = rule
    return best


def respond(target: str, rule: dict, notice: str = "") -> None:
    label = f"{rule.get('reason', '보호 경로')}, 규칙 `{rule['pattern']}`"
    if rule["mode"] == "block":
        reason = (f"보호 경로({label}): {target}. AI가 직접 고치지 않는 파일이다. "
                  "변경이 필요하면 이유를 사용자에게 설명하고 사람이 직접 수정하게 한다.")
        decision = "deny"
    else:
        reason = f"보호 경로({label}): {target}. 사용자 확인 후 진행한다."
        decision = "ask"
    if notice:
        reason += f" (주의: {notice})"
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason,
    }}, ensure_ascii=False))


def main() -> int:
    common.setup_streams()
    try:
        payload = common.read_payload()
    except ValueError as exc:
        print(f"harness protect-paths: 입력을 읽지 못해 보호 경로 검사가 꺼진 상태다: {exc}", file=sys.stderr)
        return 1
    key = TOOL_PATH_KEYS.get(payload.get("tool_name"))
    tool_input = payload.get("tool_input")
    raw = tool_input.get(key) if key and isinstance(tool_input, dict) else None
    if not isinstance(raw, str) or not raw.strip():
        return 0
    project = common.project_dir(payload)
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else None
    kind, where = common.classify_path(project, raw, cwd)

    if kind == "unc":
        rule = {"pattern": "\\\\server\\share", "mode": "ask", "reason": "프로젝트 소속을 확인할 수 없는 네트워크 경로"}
        target = raw
    elif kind == "outside":
        if not common.is_user_settings(where):
            return 0
        rule = {"pattern": "~/.claude/settings*.json", "mode": "ask", "reason": "사용자 hooks 설정"}
        target = str(where)
    else:
        target = where
        notice = ""
        try:
            config = common.load_config(project)
            rules = rules_for(config)
        except Exception as exc:  # noqa: BLE001 - 어떤 설정 오류에서도 끌 수 없는 규칙은 남긴다
            rules, notice = rules_for(None), f"{OFF_NOTICE}: {exc}"
        rule = decide(target, rules)
        if rule is None:
            if notice:
                print(f"harness protect-paths: {notice}", file=sys.stderr)
                return 1
            return 0
        respond(target, rule, notice)
        log(project, payload, rule, target)
        return 0

    respond(target, rule)
    log(project, payload, rule, target)
    return 0


def log(project, payload, rule, target) -> None:
    common.log_event(project, {
        "hook": "protect-paths", "decision": rule["mode"], "rule": rule["pattern"],
        "path": target, "tool": payload.get("tool_name"), "session": payload.get("session_id"),
    })


if __name__ == "__main__":
    sys.exit(main())
