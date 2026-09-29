#!/usr/bin/env python3
"""ai-dev-harness 명령 진입점. 표준 라이브러리만 사용한다.

    python bin/harness.py init <target> [--project-name ..] [--platform gitlab|github]
                               [--tracker jira|github] [--issue-prefix KEY] [--force]
    python bin/harness.py init --self        # 키트 저장소 자신에게 템플릿을 다시 생성
    python bin/harness.py check <target>     # 렌더링 결과와 실제 파일의 차이(드리프트) 검사
    python bin/harness.py check --self
    python bin/harness.py version
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

VERSION = "0.1.0"
KIT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = KIT_ROOT / "core" / "templates"
MANIFEST_PATH = TEMPLATES_DIR / "manifest.json"
CONFIG_NAME = "harness.json"

PLATFORMS = {
    "gitlab": {
        "platform": "GitLab",
        "pr_noun": "MR",
        "pr_long": "Merge Request",
        "ci_variables": "GitLab CI/CD Variables",
    },
    "github": {
        "platform": "GitHub",
        "pr_noun": "PR",
        "pr_long": "Pull Request",
        "ci_variables": "GitHub Actions Secrets",
    },
}

TRACKERS = {
    "jira": {
        "tracker_name": "Jira",
        "issue_noun": "Jira 업무 항목",
        "issue_key": "Jira Issue Key",
    },
    "github": {
        "tracker_name": "GitHub Issues",
        "issue_noun": "GitHub 이슈",
        "issue_key": "이슈 번호",
    },
}

CONSUMER_RELATED_DOCS = [
    {"label": "문서 역할과 우선순위", "path": "docs/README.md"},
    {"label": "AI 병렬 작업 및 충돌 방지 규칙", "path": "docs/ai-collaboration.md"},
    {"label": "Git 컨벤션(브랜치·커밋·병합 요청)", "path": "docs/git-convention.md"},
    {"label": "개발 흐름(업무 항목 시작부터 병합까지)", "path": "docs/development-workflow.md"},
    {"label": "Secret 및 환경변수 관리 규칙", "path": "docs/secret-environment-variables.md"},
]

PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


class HarnessError(Exception):
    """사용자에게 그대로 보여 줄 오류."""


# ---------------------------------------------------------------------------
# 설정과 컨텍스트
# ---------------------------------------------------------------------------


def load_config(path: Path) -> dict:
    if not path.is_file():
        raise HarnessError(f"설정 파일이 없다: {path}")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HarnessError(f"설정 파일 JSON 오류: {path}: {exc}") from exc
    validate_config(config, path)
    return config


def validate_config(config: dict, source: Path | str) -> None:
    required = ["project_name", "platform", "tracker", "default_branch", "integration_branch"]
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise HarnessError(f"{source}: 필수 항목이 비어 있다: {', '.join(missing)}")
    if config["platform"] not in PLATFORMS:
        raise HarnessError(f"{source}: platform은 {sorted(PLATFORMS)} 중 하나여야 한다")
    if config["tracker"] not in TRACKERS:
        raise HarnessError(f"{source}: tracker는 {sorted(TRACKERS)} 중 하나여야 한다")
    if config["tracker"] == "jira" and not config.get("issue_prefix"):
        raise HarnessError(f"{source}: tracker가 jira이면 issue_prefix(예: ABC123)가 필요하다")
    docs = config.get("related_docs", [])
    if not isinstance(docs, list) or any(
        not isinstance(d, dict) or not d.get("label") or not d.get("path") for d in docs
    ):
        raise HarnessError(f"{source}: related_docs는 label·path를 가진 객체 목록이어야 한다")


def build_context(config: dict) -> dict:
    ctx = {
        "project_name": config["project_name"],
        "default_branch": config["default_branch"],
        "integration_branch": config["integration_branch"],
    }
    ctx.update(PLATFORMS[config["platform"]])
    ctx.update(TRACKERS[config["tracker"]])
    prefix = config.get("issue_prefix", "")
    if config["tracker"] == "jira":
        ctx["issue_key_example"] = f"{prefix}-52"
        ctx["branch_key_example"] = f"{prefix}-52"
    else:
        ctx["issue_key_example"] = "#52"
        ctx["branch_key_example"] = "52"
    docs = config.get("related_docs") or []
    ctx["related_docs"] = "\n".join(f"- [{d['label']}]({d['path']})" for d in docs)
    return ctx


def render(text: str, ctx: dict, source: str = "<template>") -> str:
    unknown: list[str] = []

    def substitute(match: re.Match) -> str:
        key = match.group(1)
        if key not in ctx:
            unknown.append(key)
            return match.group(0)
        return ctx[key]

    rendered = PLACEHOLDER.sub(substitute, text)
    if unknown:
        raise HarnessError(f"{source}: 알 수 없는 자리표시자: {', '.join(sorted(set(unknown)))}")
    return rendered


# ---------------------------------------------------------------------------
# 매니페스트와 렌더링 계획
# ---------------------------------------------------------------------------


def load_manifest() -> list[dict]:
    if not MANIFEST_PATH.is_file():
        raise HarnessError(f"매니페스트가 없다: {MANIFEST_PATH}")
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return data["files"]


def planned_files(config: dict, self_mode: bool) -> list[tuple[str, str]]:
    """(템플릿 상대 경로, 대상 상대 경로) 목록."""
    plan = []
    for entry in load_manifest():
        wanted_platform = entry.get("platform")
        if wanted_platform and wanted_platform != config["platform"]:
            continue
        if self_mode and not entry.get("self", False):
            continue
        plan.append((entry["src"], entry["dest"]))
    return plan


def render_all(config: dict, self_mode: bool) -> dict[str, str]:
    ctx = build_context(config)
    outputs: dict[str, str] = {}
    for src, dest in planned_files(config, self_mode):
        path = TEMPLATES_DIR / src
        if not path.is_file():
            raise HarnessError(f"템플릿 파일이 없다: {path}")
        outputs[dest] = render(path.read_text(encoding="utf-8"), ctx, source=src)
    return outputs


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


# ---------------------------------------------------------------------------
# 명령
# ---------------------------------------------------------------------------


def resolve_target(args) -> tuple[Path, bool]:
    if args.self:
        return KIT_ROOT, True
    if not args.target:
        raise HarnessError("대상 디렉터리 또는 --self 가 필요하다")
    return Path(args.target).resolve(), False


def config_from_args(args, target: Path) -> dict:
    if args.config:
        return load_config(Path(args.config))
    existing = target / CONFIG_NAME
    if existing.is_file():
        return load_config(existing)
    config = {
        "harness_version": VERSION,
        "project_name": args.project_name or target.name,
        "platform": args.platform,
        "tracker": args.tracker,
        "issue_prefix": args.issue_prefix or "",
        "default_branch": args.default_branch,
        "integration_branch": args.integration_branch,
        "related_docs": CONSUMER_RELATED_DOCS,
    }
    validate_config(config, "명령 인자")
    return config


def cmd_init(args) -> int:
    target, self_mode = resolve_target(args)
    if self_mode:
        config = load_config(KIT_ROOT / CONFIG_NAME)
    else:
        config = config_from_args(args, target)
    outputs = render_all(config, self_mode)

    if not self_mode and not args.force:
        collisions = [dest for dest in outputs if (target / dest).exists()]
        if collisions:
            listing = "\n".join(f"  {c}" for c in collisions)
            raise HarnessError(
                "이미 존재하는 파일이 있어 중단한다. 덮어쓰려면 --force 를 지정한다:\n" + listing
            )

    target.mkdir(parents=True, exist_ok=True)
    for dest, content in outputs.items():
        write_text(target / dest, content)
    if not self_mode:
        config_path = target / CONFIG_NAME
        if not config_path.exists() or args.force:
            config["harness_version"] = VERSION
            write_text(config_path, json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    print(f"{len(outputs)}개 파일을 {target} 에 생성했다.")
    for dest in outputs:
        print(f"  {dest}")
    return 0


def cmd_check(args) -> int:
    target, self_mode = resolve_target(args)
    config = load_config(target / CONFIG_NAME)
    recorded = config.get("harness_version")
    if recorded and recorded != VERSION:
        print(f"주의: 설정의 harness_version {recorded} 과 키트 {VERSION} 이 다르다.")
    outputs = render_all(config, self_mode)
    missing, drifted = [], []
    for dest, content in outputs.items():
        path = target / dest
        if not path.is_file():
            missing.append(dest)
        elif path.read_text(encoding="utf-8").replace("\r\n", "\n") != content:
            drifted.append(dest)
    if not missing and not drifted:
        print(f"드리프트 없음: {len(outputs)}개 파일이 템플릿과 일치한다.")
        return 0
    for dest in missing:
        print(f"없음:   {dest}")
    for dest in drifted:
        print(f"불일치: {dest}")
    print("템플릿을 고친 뒤 `init --self`(또는 `init <target> --force`)로 다시 생성한다.")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="대상 저장소에 규칙 파일을 생성한다")
    init.add_argument("target", nargs="?")
    init.add_argument("--self", action="store_true", help="키트 저장소 자신에게 적용")
    init.add_argument("--config", help="사용할 harness.json 경로")
    init.add_argument("--project-name")
    init.add_argument("--platform", choices=sorted(PLATFORMS), default="gitlab")
    init.add_argument("--tracker", choices=sorted(TRACKERS), default="jira")
    init.add_argument("--issue-prefix", help="Jira 프로젝트 키(예: ABC123)")
    init.add_argument("--default-branch", default="main")
    init.add_argument("--integration-branch", default="develop")
    init.add_argument("--force", action="store_true", help="기존 파일을 덮어쓴다")
    init.set_defaults(func=cmd_init)

    check = sub.add_parser("check", help="생성된 파일이 템플릿과 일치하는지 검사한다")
    check.add_argument("target", nargs="?")
    check.add_argument("--self", action="store_true")
    check.set_defaults(func=cmd_check)

    version = sub.add_parser("version")
    version.set_defaults(func=lambda _args: print(VERSION) or 0)

    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # Windows 콘솔에서도 한국어 메시지를 깨지지 않게 출력한다
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        return args.func(args)
    except HarnessError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
