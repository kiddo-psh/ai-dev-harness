#!/usr/bin/env python3
"""ai-dev-harness 명령 진입점. 표준 라이브러리만 사용한다.

    python bin/harness.py init <target> [--project-name ..] [--platform gitlab|github]
                               [--tracker jira|github] [--issue-prefix KEY] [--force]
    python bin/harness.py init --self        # 키트 저장소 자신에게 템플릿을 다시 생성
    python bin/harness.py init <target> --area <dir> --verify-cmd <cmd> [--verify-cmd ..]
                               [--trigger ..] [--review-focus ..] [--area-doc ..] [--force]
                                             # 영역 디렉터리에 AGENTS.md 생성(루트 init 이후)
    python bin/harness.py check <target>     # 렌더링 결과와 실제 파일의 차이(드리프트) 검사
    python bin/harness.py check --self
    python bin/harness.py version
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

VERSION = "0.2.0"
KIT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = KIT_ROOT / "core" / "templates"
HOOKS_DIR = KIT_ROOT / "core" / "hooks"
# 매니페스트 항목의 base가 가리키는 원본 디렉터리
SOURCE_DIRS = {"templates": TEMPLATES_DIR, "hooks": HOOKS_DIR}
MANIFEST_PATH = TEMPLATES_DIR / "manifest.json"
AREA_TEMPLATE = "AREA-AGENTS.md"
AREA_KEYS = {"dir", "verify", "triggers", "review_focus", "docs"}
CONFIG_KEYS = {"harness_version", "project_name", "platform", "tracker", "issue_prefix",
               "default_branch", "integration_branch", "related_docs", "areas", "hooks"}
RELATED_DOC_KEYS = {"label", "path"}
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

# 루트 init 인자의 기본값. argparse 기본값을 None으로 두어 사용자가 직접 준 인자를 구분한다.
ROOT_DEFAULTS = {
    "platform": "gitlab",
    "tracker": "jira",
    "default_branch": "main",
    "integration_branch": "develop",
}
ROOT_ONLY_FLAGS = ("config", "project_name", "issue_prefix", *ROOT_DEFAULTS)

CONSUMER_RELATED_DOCS = [
    {"label": "문서 역할과 우선순위", "path": "docs/README.md"},
    {"label": "AI 병렬 작업 및 충돌 방지 규칙", "path": "docs/ai-collaboration.md"},
    {"label": "Git 컨벤션(브랜치·커밋·병합 요청)", "path": "docs/git-convention.md"},
    {"label": "개발 흐름(업무 항목 시작부터 병합까지)", "path": "docs/development-workflow.md"},
    {"label": "Secret 및 환경변수 관리 규칙", "path": "docs/secret-environment-variables.md"},
]

# 영역 AGENTS.md의 기본 트리거. 스택 중립 항목만 두고 스택 고유 항목은 프로필이 채운다.
DEFAULT_TRIGGERS = [
    "계약 문서(API·스키마·영역 간 교환 계약)의 변경, 또는 계약과 다른 구현",
    "DB 마이그레이션",
    "인증·인가, 토큰·세션·쿠키 처리",
    "트랜잭션 경계의 신설·변경, 여러 저장소에 걸친 쓰기, 외부 시스템(메시지·캐시) 쓰기와 그 재시도·멱등성·부분 실패 처리",
    "공용 모듈 또는 다른 담당자 소유 영역의 생산 코드",
    "의존성·lock 파일, 운영 설정, 환경 변수 계약, CI 정의",
]

DEFAULT_REVIEW_FOCUS = [
    "계약 정합성",
    "정확성(경계 조건, 실패 경로)",
    "보안(입력 검증, Secret)",
    "테스트 실효성(플랜 목록과 실제 테스트의 대조)",
]

# 존재를 확인할 수 없는 문서를 기본값으로 적지 않는다. 렌더링은 설정만으로 정해져야 check가 안정적이다.
NO_AREA_DOCS = "- 아직 지정한 기준 문서가 없다. 계약·스키마·컨벤션 문서가 생기면 `--area-doc`으로 추가한다."

# hooks 설정 검증은 대상에 복사되는 hook 공통 코드와 같은 규칙을 쓴다
_HOOKS_SPEC = importlib.util.spec_from_file_location("harness_hooks_common", HOOKS_DIR / "harness_common.py")
hooks_common = importlib.util.module_from_spec(_HOOKS_SPEC)
_HOOKS_SPEC.loader.exec_module(hooks_common)

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
    if not isinstance(config, dict):
        raise HarnessError(f"{source}: 최상위 설정은 객체여야 한다")
    unknown = sorted(set(config) - CONFIG_KEYS)
    if unknown:
        raise HarnessError(f"{source}: 알 수 없는 설정 키: {', '.join(unknown)}")
    required = ["project_name", "platform", "tracker", "default_branch", "integration_branch"]
    missing = [key for key in required if not isinstance(config.get(key), str) or not config[key].strip()]
    if missing:
        raise HarnessError(f"{source}: 필수 항목이 비어 있다: {', '.join(missing)}")
    for key in ("harness_version", "issue_prefix"):
        if key in config and not isinstance(config[key], str):
            raise HarnessError(f"{source}: {key}는 문자열이어야 한다")
    if config["platform"] not in PLATFORMS:
        raise HarnessError(f"{source}: platform은 {sorted(PLATFORMS)} 중 하나여야 한다")
    if config["tracker"] not in TRACKERS:
        raise HarnessError(f"{source}: tracker는 {sorted(TRACKERS)} 중 하나여야 한다")
    if config["tracker"] == "jira" and not config.get("issue_prefix"):
        raise HarnessError(f"{source}: tracker가 jira이면 issue_prefix(예: ABC123)가 필요하다")
    docs = config.get("related_docs", [])
    if not isinstance(docs, list) or any(
        not isinstance(d, dict) or set(d) != RELATED_DOC_KEYS or
        any(not isinstance(d[key], str) or not d[key].strip() for key in RELATED_DOC_KEYS)
        for d in docs
    ):
        raise HarnessError(f"{source}: related_docs는 label·path를 가진 객체 목록이어야 한다")
    validate_areas(config.get("areas", []), source)
    try:
        hooks_common.validate_hooks(config.get("hooks"), source)
    except hooks_common.ConfigError as exc:
        raise HarnessError(str(exc)) from exc


def normalize_area_dir(value: str, source: Path | str) -> str:
    """대상 저장소 안의 상대 경로만 허용하고 `a/b` 형태로 정규화한다."""
    raw = value.strip().replace("\\", "/") if isinstance(value, str) else ""
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise HarnessError(f"{source}: 영역 dir은 대상 저장소 안의 상대 경로여야 한다: {value!r}")
    if not parts or ".." in parts:
        raise HarnessError(f"{source}: 영역 dir은 대상 저장소 안의 상대 경로여야 한다: {value!r}")
    return "/".join(parts)


def validate_areas(areas, source: Path | str) -> None:
    if not isinstance(areas, list):
        raise HarnessError(f"{source}: areas는 목록이어야 한다")
    seen = set()
    for area in areas:
        if not isinstance(area, dict) or "dir" not in area:
            raise HarnessError(f"{source}: areas 항목에는 dir이 필요하다")
        dir_ = normalize_area_dir(area["dir"], source)
        if dir_ != area["dir"]:
            raise HarnessError(f"{source}: 영역 dir은 정규화된 형태여야 한다: {area['dir']!r} → {dir_!r}")
        if dir_ in seen:
            raise HarnessError(f"{source}: 영역 dir이 중복된다: {dir_}")
        seen.add(dir_)
        unknown = sorted(set(area) - AREA_KEYS)
        if unknown:  # 오타 난 키가 조용히 무시되고 기본값이 적용되는 것을 막는다
            raise HarnessError(f"{source}: 영역 {dir_}에 알 수 없는 키가 있다: {', '.join(unknown)}")
        for key, required in (("verify", True), ("triggers", False),
                              ("review_focus", False), ("docs", False)):
            if key not in area and not required:
                continue
            items = area.get(key)
            if not isinstance(items, list) or not items or any(
                not isinstance(item, str) or not item.strip() for item in items
            ):
                raise HarnessError(f"{source}: 영역 {dir_}의 {key}는 비어 있지 않은 문자열 목록이어야 한다")


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
    ctx["hook_python"] = (config.get("hooks") or {}).get("python", hooks_common.DEFAULT_PYTHON)
    return ctx


def area_context(area: dict) -> dict:
    dir_ = area["dir"]
    docs = area.get("docs")
    triggers = area.get("triggers") or DEFAULT_TRIGGERS
    focus = area.get("review_focus") or DEFAULT_REVIEW_FOCUS
    return {
        "area_dir": dir_,
        "area_docs": "\n".join(f"- `{doc}`" for doc in docs) if docs else NO_AREA_DOCS,
        "area_verify": "\n".join(f"- `{cmd}`" for cmd in area["verify"]),
        "area_triggers": "\n".join(f"{i}. {item}" for i, item in enumerate(triggers, 1)),
        "area_review_focus": " · ".join(focus),
    }


def render_area(area: dict, ctx: dict) -> str:
    path = TEMPLATES_DIR / AREA_TEMPLATE
    if not path.is_file():
        raise HarnessError(f"템플릿 파일이 없다: {path}")
    return render(path.read_text(encoding="utf-8"), {**ctx, **area_context(area)}, source=AREA_TEMPLATE)


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
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HarnessError(f"매니페스트를 읽을 수 없다: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        raise HarnessError("매니페스트 files는 목록이어야 한다")
    seen = set()
    for entry in data["files"]:
        if not isinstance(entry, dict) or not {"src", "dest"} <= set(entry) or set(entry) - {"src", "dest", "base", "platform", "self", "render"}:
            raise HarnessError("매니페스트 항목의 키가 잘못됐다")
        base = entry.get("base", "templates")
        if not isinstance(base, str) or base not in SOURCE_DIRS:
            raise HarnessError(f"매니페스트 base는 {sorted(SOURCE_DIRS)} 중 하나여야 한다: {base}")
        for key in ("src", "dest"):
            value = entry[key]
            if (not isinstance(value, str) or not value or "\\" in value or
                    value.startswith("/") or any(part in ("", ".", "..") for part in value.split("/")) or
                    re.match(r"^[A-Za-z]:", value)):
                raise HarnessError(f"매니페스트 {key} 경로가 잘못됐다: {value!r}")
        if entry["dest"] in seen:
            raise HarnessError(f"매니페스트 목적지가 중복된다: {entry['dest']}")
        seen.add(entry["dest"])
        if ("platform" in entry and (not isinstance(entry["platform"], str) or entry["platform"] not in PLATFORMS) or
                any(key in entry and not isinstance(entry[key], bool) for key in ("self", "render"))):
            raise HarnessError(f"매니페스트 선택 값이 잘못됐다: {entry['dest']}")
    return data["files"]


def planned_files(config: dict, self_mode: bool) -> list[tuple[Path, str, bool]]:
    """(원본 경로, 대상 상대 경로, 자리표시자 치환 여부) 목록."""
    plan = []
    for entry in load_manifest():
        wanted_platform = entry.get("platform")
        if wanted_platform and wanted_platform != config["platform"]:
            continue
        if self_mode and not entry.get("self", False):
            continue
        base = entry.get("base", "templates")
        if base not in SOURCE_DIRS:
            raise HarnessError(f"매니페스트 base는 {sorted(SOURCE_DIRS)} 중 하나여야 한다: {base}")
        plan.append((SOURCE_DIRS[base] / entry["src"], entry["dest"], entry.get("render", True)))
    return plan


def render_all(config: dict, self_mode: bool) -> dict[str, str]:
    ctx = build_context(config)
    outputs: dict[str, str] = {}
    for path, dest, rendered in planned_files(config, self_mode):
        if not path.is_file():
            raise HarnessError(f"템플릿 파일이 없다: {path}")
        text = path.read_text(encoding="utf-8")
        outputs[dest] = render(text, ctx, source=path.name) if rendered else text
    for area in config.get("areas", []):
        outputs[f"{area['dir']}/AGENTS.md"] = render_area(area, ctx)
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
        conflicting = [flag for flag in ROOT_ONLY_FLAGS if flag != "config" and getattr(args, flag) is not None]
        if conflicting:
            raise HarnessError(f"--config 와 루트 설정 인자를 함께 쓸 수 없다: {', '.join(conflicting)}")
        return load_config(Path(args.config))
    existing = target / CONFIG_NAME
    if existing.is_file():
        conflicting = [flag for flag in ROOT_ONLY_FLAGS if flag != "config" and getattr(args, flag) is not None]
        if conflicting:
            raise HarnessError(f"기존 {CONFIG_NAME} 과 루트 설정 인자를 함께 쓸 수 없다: {', '.join(conflicting)}")
        return load_config(existing)
    config = {
        "harness_version": VERSION,
        "project_name": args.project_name or target.name,
        "platform": args.platform or ROOT_DEFAULTS["platform"],
        "tracker": args.tracker or ROOT_DEFAULTS["tracker"],
        "issue_prefix": args.issue_prefix or "",
        "default_branch": args.default_branch or ROOT_DEFAULTS["default_branch"],
        "integration_branch": args.integration_branch or ROOT_DEFAULTS["integration_branch"],
        "related_docs": CONSUMER_RELATED_DOCS,
    }
    validate_config(config, "명령 인자")
    return config


def cmd_init_area(args, target: Path) -> int:
    if not args.verify_cmd:
        raise HarnessError("--area 에는 --verify-cmd 가 하나 이상 필요하다")
    given = [flag for flag in ROOT_ONLY_FLAGS if getattr(args, flag) is not None]
    if given:  # 영역 모드는 대상의 harness.json만 쓴다. 루트 인자를 조용히 버리지 않는다
        flags = ", ".join(f"--{flag.replace('_', '-')}" for flag in given)
        raise HarnessError(f"--area 는 대상의 {CONFIG_NAME} 설정을 쓰므로 {flags} 를 함께 쓸 수 없다")
    config_path = target / CONFIG_NAME
    if not config_path.is_file():
        raise HarnessError(f"{config_path} 이 없다. 루트 init 을 먼저 실행한다")
    config = load_config(config_path)
    area = {"dir": normalize_area_dir(args.area, "--area"), "verify": args.verify_cmd}
    areas = list(config.get("areas", []))
    same = [i for i, existing in enumerate(areas) if existing.get("dir") == area["dir"]]
    previous = areas[same[0]] if same else {}
    area["triggers"] = args.trigger or previous.get("triggers") or list(DEFAULT_TRIGGERS)
    area["review_focus"] = args.review_focus or previous.get("review_focus") or list(DEFAULT_REVIEW_FOCUS)
    if args.area_doc or previous.get("docs"):
        area["docs"] = args.area_doc or previous["docs"]
    if same:
        areas[same[0]] = area  # 같은 영역을 다시 생성하면 기존 항목을 제자리에서 바꾼다
    else:
        areas.append(area)
    config["areas"] = areas
    validate_config(config, "명령 인자")

    content = render_area(area, build_context(config))
    dest = target / area["dir"] / "AGENTS.md"
    if dest.exists() and not args.force:
        raise HarnessError(f"이미 존재하는 파일이 있어 중단한다. 덮어쓰려면 --force 를 지정한다:\n  {dest}")
    write_text(dest, content)
    write_text(config_path, json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    print(f"영역 {area['dir']} 에 AGENTS.md 를 생성하고 {CONFIG_NAME} 의 areas 를 갱신했다.")
    return 0


def cmd_init(args) -> int:
    target, self_mode = resolve_target(args)
    if args.area is not None:
        return cmd_init_area(args, target)
    for flag in ("verify_cmd", "trigger", "review_focus", "area_doc"):
        if getattr(args, flag):
            raise HarnessError(f"--{flag.replace('_', '-')} 는 --area 와 함께 쓴다")
    if self_mode:
        given = [flag for flag in ROOT_ONLY_FLAGS if getattr(args, flag) is not None]
        if given:
            raise HarnessError(f"--self 는 루트 설정 인자를 함께 쓸 수 없다: {', '.join(given)}")
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
    version_drift = recorded != VERSION
    if version_drift:
        print(f"버전 불일치: 설정의 harness_version {recorded!r} 과 키트 {VERSION} 이 다르다.")
    outputs = render_all(config, self_mode)
    missing, drifted = [], []
    for dest, content in outputs.items():
        path = target / dest
        if not path.is_file():
            missing.append(dest)
        elif path.read_text(encoding="utf-8").replace("\r\n", "\n") != content:
            drifted.append(dest)
    hooks_dir = target / ".claude" / "hooks"
    expected_hooks = {Path(dest).name for dest in outputs if dest.startswith(".claude/hooks/")}
    extra_hooks = sorted(p.relative_to(target).as_posix() for p in hooks_dir.iterdir()
                         if p.name not in expected_hooks) if hooks_dir.is_dir() else []
    if not missing and not drifted and not extra_hooks and not version_drift:
        print(f"드리프트 없음: {len(outputs)}개 파일이 템플릿과 일치한다.")
        return 0
    for dest in missing:
        print(f"없음:   {dest}")
    for dest in drifted:
        print(f"불일치: {dest}")
    for dest in extra_hooks:
        print(f"여분:   {dest}")
    if extra_hooks:
        print("관리 hook 디렉터리의 여분 항목을 확인하고 제거한다.")
    if version_drift or missing or drifted:
        print("설정과 템플릿을 확인한 뒤 `init --self`(또는 `init <target> --force`)로 다시 생성한다.")
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
    init.add_argument("--platform", choices=sorted(PLATFORMS), help="기본 gitlab")
    init.add_argument("--tracker", choices=sorted(TRACKERS), help="기본 jira")
    init.add_argument("--issue-prefix", help="Jira 프로젝트 키(예: ABC123)")
    init.add_argument("--default-branch", help="기본 main")
    init.add_argument("--integration-branch", help="기본 develop")
    init.add_argument("--force", action="store_true", help="기존 파일을 덮어쓴다")
    init.add_argument("--area", help="영역 디렉터리(대상 저장소 기준 상대 경로)에 AGENTS.md 생성")
    init.add_argument("--verify-cmd", action="append", help="영역 검증 명령(반복 가능, --area 필수)")
    init.add_argument("--trigger", action="append", help="엄격 단계 트리거(반복 가능, 지정하면 기본값 대체)")
    init.add_argument("--review-focus", action="append", help="리뷰 관점(반복 가능, 지정하면 기본값 대체)")
    init.add_argument("--area-doc", action="append", help="영역 기준 문서 경로(반복 가능)")
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
