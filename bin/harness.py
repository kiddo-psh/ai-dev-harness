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
    python bin/harness.py judge [<target>|--self] [--base <ref> | --files <목록 파일|->] [--json]
                                             # 변경 파일로 경량·표준·엄격(lite·standard·strict) 판정
    python bin/harness.py classify-ci --jobs <jobs.json> [--trace-dir <dir>] [--out <file.jsonl>]
                                             # 실패한 CI job의 원인 범주를 JSONL로 산출(trace는 <job_id>.log)
    python bin/harness.py lint-plans [<key>] [--target <dir> | --self]
                                             # plans/의 플랜·리뷰 파일 검사(실패 1, 경고만이면 0)
    python bin/harness.py version
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import re
import sys
from pathlib import Path

VERSION = "0.2.0"
KIT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = KIT_ROOT / "core" / "templates"
HOOKS_DIR = KIT_ROOT / "core" / "hooks"
CI_DIR = KIT_ROOT / "core" / "ci"
METRICS_DIR = KIT_ROOT / "core" / "metrics"
# 매니페스트 항목의 base가 가리키는 원본 디렉터리
SOURCE_DIRS = {"templates": TEMPLATES_DIR, "hooks": HOOKS_DIR, "ci": CI_DIR}
# 매니페스트 항목의 requires가 가리킬 수 있는 설정 키. 설정에 그 키가 있을 때만 생성한다
OPTIONAL_BLOCKS = {"claude_review"}
MANIFEST_PATH = TEMPLATES_DIR / "manifest.json"
AREA_TEMPLATE = "AREA-AGENTS.md"
AREA_KEYS = {"dir", "verify", "triggers", "review_focus", "docs", "trigger_paths", "test_paths"}
CONFIG_KEYS = {"harness_version", "project_name", "platform", "tracker", "issue_prefix",
               "default_branch", "integration_branch", "related_docs", "areas", "hooks", "judge", "claude_review"}
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

# 영역 AGENTS.md의 기본 트리거. 판정의 사람 확인 목록과 같은 값이라 hook 공통 코드에 둔다
DEFAULT_TRIGGERS = list(hooks_common.DEFAULT_AREA_TRIGGERS)

# claude_review 검증은 대상에 복사되는 리뷰 공통 코드와 같은 규칙을 쓴다
_REVIEW_SPEC = importlib.util.spec_from_file_location("harness_review_common",
                                                      CI_DIR / "claude-review" / "review_common.py")
review_common = importlib.util.module_from_spec(_REVIEW_SPEC)
_REVIEW_SPEC.loader.exec_module(review_common)

# CI 실패 분류는 M4-1 수집기도 쓰는 core/metrics 모듈에 둔다
_CLASSIFY_SPEC = importlib.util.spec_from_file_location("harness_classify_ci", METRICS_DIR / "classify_ci.py")
classify_ci = importlib.util.module_from_spec(_CLASSIFY_SPEC)
_CLASSIFY_SPEC.loader.exec_module(classify_ci)

PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
PLACEHOLDER_NAME = re.compile(r"[a-z_]+")


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
    if config["tracker"] == "jira" and not config.get("issue_prefix", "").strip():
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
        if "hooks" in config:  # 키를 생략하면 기본값, 명시한 null은 객체 계약 위반이다
            hooks_common.validate_hooks(config["hooks"], source)
        if "judge" in config:
            hooks_common.validate_judge_root(config["judge"], source)
    except hooks_common.ConfigError as exc:
        raise HarnessError(str(exc)) from exc
    if "claude_review" in config:  # 생략하면 리뷰 파일을 만들지 않는다. 명시한 null은 객체 계약 위반이다
        if config["platform"] != "gitlab":
            raise HarnessError(f"{source}: claude_review는 platform이 gitlab일 때만 쓴다")
        try:
            review_common.validate_policy(config["claude_review"], str(source))
        except review_common.PolicyError as exc:
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
        try:
            hooks_common.validate_judge_rules(area, source)
        except hooks_common.ConfigError as exc:
            raise HarnessError(str(exc)) from exc


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
    for include in load_includes():  # 다른 파일의 절을 자리표시자 값으로 넣는다. 포함 내용도 같은 컨텍스트로 렌더한다
        if include["name"] in ctx:
            raise HarnessError(f"매니페스트 include 이름이 기존 자리표시자와 겹친다: {include['name']}")
        ctx[include["name"]] = render(include_text(include), ctx, source=f"{include['src']}#{include['name']}")
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
    unmatched = PLACEHOLDER.sub("", text)
    if "{{" in unmatched or "}}" in unmatched:
        raise HarnessError(f"{source}: 잘못된 자리표시자 형식")
    return rendered


# ---------------------------------------------------------------------------
# 매니페스트와 렌더링 계획
# ---------------------------------------------------------------------------


def read_manifest() -> dict:
    if not MANIFEST_PATH.is_file():
        raise HarnessError(f"매니페스트가 없다: {MANIFEST_PATH}")
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HarnessError(f"매니페스트를 읽을 수 없다: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        raise HarnessError("매니페스트 files는 목록이어야 한다")
    return data


def valid_template_path(value) -> bool:
    return (isinstance(value, str) and bool(value) and "\\" not in value and not value.startswith("/") and
            all(part not in ("", ".", "..") for part in value.split("/")) and not re.match(r"^[A-Za-z]:", value))


def load_includes() -> list[dict]:
    """매니페스트 includes: 원본 파일(templates 기준)의 `## 절`을 골라 자리표시자 값으로 쓴다."""
    includes = read_manifest().get("includes", [])
    if not isinstance(includes, list):
        raise HarnessError("매니페스트 includes는 목록이어야 한다")
    seen = set()
    for entry in includes:
        if not isinstance(entry, dict) or not {"name", "src", "sections"} <= set(entry) <= {"name", "src", "sections", "tag"}:
            raise HarnessError("매니페스트 include 항목은 name·src·sections(선택 tag)를 가져야 한다")
        if "tag" in entry and (not isinstance(entry["tag"], str) or not re.fullmatch(r"[^\[\]\s]+", entry["tag"])):
            raise HarnessError(f"매니페스트 include tag가 잘못됐다: {entry['tag']!r}")
        name = entry["name"]
        if not isinstance(name, str) or not PLACEHOLDER_NAME.fullmatch(name):
            raise HarnessError(f"매니페스트 include 이름은 소문자와 밑줄만 쓴다: {name!r}")
        if name.startswith("area_"):  # 영역 자리표시자 이름공간. 영역 문서에서 조용히 가려지는 것을 막는다
            raise HarnessError(f"매니페스트 include 이름은 area_로 시작할 수 없다: {name}")
        if name in seen:
            raise HarnessError(f"매니페스트 include 이름이 중복된다: {name}")
        seen.add(name)
        if not valid_template_path(entry["src"]):
            raise HarnessError(f"매니페스트 include src 경로가 잘못됐다: {entry['src']!r}")
        sections = entry["sections"]
        if not isinstance(sections, list) or not sections or any(
                not isinstance(s, str) or not s.strip() for s in sections):
            raise HarnessError(f"매니페스트 include {name}의 sections는 비어 있지 않은 문자열 목록이어야 한다")
    return includes


def markdown_sections(text: str) -> dict[str, str]:
    """`## 제목` 단위 본문. 첫 `##` 앞의 설명은 버린다."""
    sections: dict[str, list[str]] = {}
    current = None
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.startswith("## "):
            current = line[3:].strip()
            if current in sections:
                raise HarnessError(f"절 제목이 중복된다: {current}")
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {name: "\n".join(lines).strip("\n") for name, lines in sections.items()}


def include_text(include: dict) -> str:
    path = TEMPLATES_DIR / include["src"]
    if not path.is_file():
        raise HarnessError(f"include 원본이 없다: {path}")
    sections = markdown_sections(path.read_text(encoding="utf-8"))
    missing = [s for s in include["sections"] if s not in sections]
    if missing:
        raise HarnessError(f"{include['src']}에 절이 없다: {', '.join(missing)}")
    text = "\n".join(sections[s] for s in include["sections"])  # 절 본문은 목록이라 한 목록으로 잇는다
    if "tag" in include:
        text = "\n".join(f"{line} [{include['tag']}]" if line.startswith("- ") else line
                         for line in text.split("\n"))
    return text


def load_manifest() -> list[dict]:
    data = read_manifest()
    seen = set()
    for entry in data["files"]:
        if not isinstance(entry, dict) or not {"src", "dest"} <= set(entry) or set(entry) - {"src", "dest", "base", "platform", "self", "render", "requires"}:
            raise HarnessError("매니페스트 항목의 키가 잘못됐다")
        base = entry.get("base", "templates")
        if not isinstance(base, str) or base not in SOURCE_DIRS:
            raise HarnessError(f"매니페스트 base는 {sorted(SOURCE_DIRS)} 중 하나여야 한다: {base}")
        for key in ("src", "dest"):
            value = entry[key]
            if not valid_template_path(value):
                raise HarnessError(f"매니페스트 {key} 경로가 잘못됐다: {value!r}")
        if entry["dest"] in seen:
            raise HarnessError(f"매니페스트 목적지가 중복된다: {entry['dest']}")
        seen.add(entry["dest"])
        if ("platform" in entry and (not isinstance(entry["platform"], str) or entry["platform"] not in PLATFORMS) or
                any(key in entry and not isinstance(entry[key], bool) for key in ("self", "render")) or
                "requires" in entry and (not isinstance(entry["requires"], str) or entry["requires"] not in OPTIONAL_BLOCKS)):
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
        if "requires" in entry and entry["requires"] not in config:  # 선택 블록이 없으면 만들지 않는다
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
    # 경로 판정 규칙도 생성 시점의 기본값을 설정에 굳힌다. 키트 기본값이 바뀌어도 기존 영역 판정은 그대로다
    area["trigger_paths"] = previous.get("trigger_paths", copy.deepcopy(hooks_common.DEFAULT_TRIGGER_PATHS))
    area["test_paths"] = previous.get("test_paths", list(hooks_common.DEFAULT_TEST_PATHS))
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


TIER_LABELS = {"lite": "경량", "standard": "표준", "strict": "엄격"}


GIT_QUOTE_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def unquote_git_path(line: str) -> str:
    """`git diff --name-only`가 비ASCII·특수 문자 경로에 쓰는 C 방식 따옴표를 푼다(`"a/\\354\\240\\225.md"`)."""
    if len(line) < 2 or not (line.startswith('"') and line.endswith('"')):
        return line
    body, out, i = line[1:-1], bytearray(), 0
    while i < len(body):
        ch = body[i]
        if ch != "\\":
            out += ch.encode("utf-8")
            i += 1
        elif re.match(r"[0-7]{3}", body[i + 1:i + 4]):
            out.append(int(body[i + 1:i + 4], 8))
            i += 4
        elif body[i + 1:i + 2] in GIT_QUOTE_ESCAPES:
            out.append(GIT_QUOTE_ESCAPES[body[i + 1]])
            i += 2
        else:
            return line  # git이 만든 형식이 아니면 그대로 둔다
    return out.decode("utf-8", errors="replace")


def read_file_list(source: str) -> list[str]:
    try:
        if source == "-":
            stream = getattr(sys.stdin, "buffer", None)
            data = stream.read() if stream is not None else sys.stdin.read().encode("utf-8")
        else:
            data = Path(source).read_bytes()
        text = data.decode("utf-8-sig")  # 메모장 등이 붙인 BOM이 첫 경로에 섞이지 않게 한다
    except OSError as exc:
        raise HarnessError(f"파일 목록을 읽을 수 없다: {source}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise HarnessError(f"파일 목록은 UTF-8이어야 한다: {source}: {exc}") from exc
    return [unquote_git_path(line.strip()) for line in text.splitlines() if line.strip()]


def cmd_judge(args) -> int:
    target, _self_mode = resolve_target(args) if args.self or args.target else (Path.cwd(), False)
    config = load_config(target / CONFIG_NAME)
    if args.files is not None:
        base, paths = None, read_file_list(args.files)
    else:
        ref = args.base or f"origin/{config['default_branch']}"
        try:
            base, paths = hooks_common.changed_files(target, ref)
        except hooks_common.ConfigError as exc:
            raise HarnessError(str(exc)) from exc
    result = {"base": base, **hooks_common.judge(paths, config)}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(f"판정: {result['tier']} ({TIER_LABELS[result['tier']]})")
    if base:
        print(f"기준: {base}")
    if not result["files"]:
        print("변경 파일 없음")
    for item in sorted(result["files"], key=lambda f: (-hooks_common.TIERS.index(f["tier"]), f["path"])):
        area = f" [{item['area']}]" if item["area"] else ""
        print(f"  {item['tier']:<8} {item['path']}{area}  {item['rule']}")
    if result["human_check"]:
        print("사람 확인 필요(경로로 판정하지 않는 트리거. 해당하면 판정을 올린다):")
        for item in result["human_check"]:
            print(f"  [{item['area'] or '영역 밖'}] {item['trigger']}")
    return 0


def cmd_classify_ci(args) -> int:
    jobs_path = Path(args.jobs)
    if not jobs_path.is_file():
        raise HarnessError(f"job 메타데이터 파일이 없다: {jobs_path}")
    trace_dir = Path(args.trace_dir) if args.trace_dir else None
    if trace_dir is not None and not trace_dir.is_dir():
        raise HarnessError(f"trace 디렉터리가 없다: {trace_dir}")
    try:
        jobs = classify_ci.load_jobs(jobs_path.read_bytes().decode("utf-8", errors="replace"))
        records, skipped = classify_ci.classify_jobs(jobs, trace_dir)
    except classify_ci.ClassifyError as exc:
        raise HarnessError(f"{jobs_path}: {exc}") from exc
    output = classify_ci.to_jsonl(records)
    if args.out:
        write_text(Path(args.out), output)
    else:
        sys.stdout.write(output)
    print(f"실패 job {len(records)}개를 분류했다. 실패가 아닌 job {skipped}개는 제외했다.", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# 플랜·리뷰 파일 lint (M2-3). 절 목록과 자리표시자는 템플릿에서 읽어 템플릿 변경을 따라간다
# ---------------------------------------------------------------------------

PLAN_TEMPLATE = "docs/templates/plan.md"
REVIEW_TEMPLATE = "docs/templates/review.md"
LINT_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
UNCHOSEN_TIER = re.compile(r"엄격\s*\\?\|\s*표준\s*\\?\|\s*경량")
TIER_VALUE = re.compile(r"엄격|표준|경량|strict|standard|lite")
TEMPLATE_PLACEHOLDER = re.compile(r"<[^<>\n]+>")
TABLE_DELIMITER = re.compile(r"\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*")
CELL_SPLIT = re.compile(r"(?<!\\)\|")
FENCE = re.compile(r"\s*(```|~~~)")
INLINE_CODE = re.compile(r"(`+).+?\1")


def strip_fences(text: str) -> list[str]:
    """코드 블록 줄을 빈 줄로 바꾼 줄 목록. 코드 블록 안의 제목·표·자리표시자는 검사하지 않는다."""
    lines, fence = [], None
    for line in text.replace("\r\n", "\n").split("\n"):
        match = FENCE.match(line)
        if fence is None and match:
            fence = match.group(1)
            lines.append("")
        elif fence is not None:
            if line.strip().startswith(fence):
                fence = None
            lines.append("")
        else:
            lines.append(line)
    return lines


def normalize_heading(title: str) -> str:
    """공백을 줄이고 끝의 괄호 주석(작성 안내)을 뗀다: `6. 변경 기록 (구현 단계에서 추기)` → `6. 변경 기록`."""
    title = re.sub(r"\s+", " ", title).strip()
    return re.sub(r"\s*\([^()]*\)$", "", title)


def lint_sections(lines: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    """(첫 `## ` 앞의 줄, 정규화한 `## ` 제목 → 본문 줄). 같은 제목은 첫 절만 쓴다."""
    head: list[str] = []
    sections: dict[str, list[str]] = {}
    current = None
    for line in lines:
        if line.startswith("## "):
            current = normalize_heading(line[3:])
            current = current if current not in sections else f"\0{len(sections)}"
            sections[current] = []
        elif current is None:
            head.append(line)
        else:
            sections[current].append(line)
    return head, sections


def table_cells(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [cell.strip() for cell in CELL_SPLIT.split(body)]


def section_tables(lines: list[str]) -> list[tuple[list[str], list[list[str]]]]:
    """절 안의 GFM 표 목록: (머리 칸, 데이터 행). 머리 행 다음에 구분줄이 와야 표로 본다."""
    tables, i = [], 0
    while i < len(lines) - 1:
        if "|" in lines[i] and "|" in lines[i + 1] and TABLE_DELIMITER.fullmatch(lines[i + 1]):
            rows, j = [], i + 2
            while j < len(lines) and "|" in lines[j] and lines[j].strip():
                rows.append(table_cells(lines[j]))
                j += 1
            tables.append((table_cells(lines[i]), rows))
            i = j
        else:
            i += 1
    return tables


def first_table(lines: list[str], header: list[str] | None = None) -> list[list[str]] | None:
    """머리 칸이 템플릿 표와 같은 표의 데이터 행. header가 없으면 첫 표. 없으면 None.

    같은 절의 다른 표(예: 대체 검증 표)를 인수 테스트 표로 잘못 읽지 않게 머리로 고른다.
    """
    for cells, rows in section_tables(lines):
        if header is None or [normalize_heading(c) for c in cells] == [normalize_heading(c) for c in header]:
            return rows
    return None


def template_spec(text: str) -> dict:
    lines = strip_fences(text)
    _head, sections = lint_sections(lines)
    placeholders = sorted({m.group(0) for line in lines for m in TEMPLATE_PLACEHOLDER.finditer(INLINE_CODE.sub("", line))})
    return {"headings": [h for h in sections if not h.startswith("\0")], "placeholders": placeholders,
            "sections": sections}


def numbered_heading(spec: dict, number: str, source: str) -> str:
    for heading in spec["headings"]:
        if heading.startswith(f"{number}. "):
            return heading
    raise HarnessError(f"{source}: 템플릿에 {number}장 절이 없다")


def lint_document(text: str, spec: dict, kind: str) -> tuple[list[str], list[str]]:
    """(실패, 경고) 메시지 목록. kind는 plan 또는 review."""
    lines = strip_fences(text)
    head, sections = lint_sections(lines)
    failures = [f"절 누락: ## {h}" for h in spec["headings"] if h not in sections]
    if kind == "plan":
        tier_lines = [line for line in head if "판정:" in line]
        if not tier_lines:
            failures.append("판정 줄(`판정:`)이 없다")
        elif len(tier_lines) > 1:
            failures.append("판정 줄(`판정:`)이 여러 개다")
        elif UNCHOSEN_TIER.search(tier_lines[0]):
            failures.append("판정을 고르지 않았다: `엄격 | 표준 | 경량`이 그대로 남았다")
        else:
            # 값은 `판정:` 뒤 첫 `·` 앞 전체다(템플릿: `> 판정: **표준** · 트리거: ...`). 강조 기호만 떼고 통째로 맞춘다
            value = tier_lines[0].split("판정:", 1)[1].split("·", 1)[0].strip().strip("*_` ").strip()
            if not TIER_VALUE.fullmatch(value):
                failures.append("판정 값은 엄격·표준·경량(strict·standard·lite) 중 하나여야 한다")
        heading = spec["acceptance"]
        if heading in sections:
            rows = first_table(sections[heading], spec.get("acceptance_header"))
            if rows is None:
                failures.append(f"## {heading}: 인수 테스트 표가 없다")
            elif not rows:
                failures.append(f"## {heading}: 인수 테스트 표에 데이터 행이 없다")
            for row in rows or []:
                if not any(row[1:]):
                    failures.append(f"## {heading}: 빈 인수 테스트 행: {row[0] or '(번호 없음)'}")
    else:
        heading = spec["measurement"]
        if heading in sections:
            rows = first_table(sections[heading], spec.get("measurement_header"))
            if rows is None:
                failures.append(f"## {heading}: 측정 표가 없다")
            elif not rows:
                failures.append(f"## {heading}: 측정 표에 데이터 행이 없다")
            for row in rows or []:
                if len(row) < 2 or not all(row[1:]):
                    failures.append(f"## {heading}: 측정 칸이 비었다: {row[0] or '(항목 없음)'}")
            # 행을 지운 것도 빈 측정 칸이다. 템플릿의 측정 항목이 모두 있어야 한다
            present = {normalize_heading(row[0]) for row in rows or [] if row}
            for label in spec.get("measurement_rows", []) if rows else []:  # 빈 표는 위에서 한 번만 보고한다
                if normalize_heading(label) not in present:
                    failures.append(f"## {heading}: 측정 항목이 없다: {label}")
    body = "\n".join(INLINE_CODE.sub("", line) for line in lines)
    warnings = [f"자리표시자가 남았다: {p}" for p in spec["placeholders"] if p in body]
    return failures, warnings


def load_lint_spec(target: Path, config: dict, rel: str, number: str, key: str) -> dict:
    """대상의 렌더된 템플릿을 쓰고, 없으면 키트 원본을 대상 설정으로 렌더한다."""
    path = target / rel
    if path.is_file():
        try:
            text, source = path.read_bytes().decode("utf-8-sig"), rel
        except (OSError, UnicodeDecodeError) as exc:
            raise HarnessError(f"템플릿을 UTF-8로 읽을 수 없다: {path}: {exc}") from exc
    else:
        original = TEMPLATES_DIR / rel
        if not original.is_file():
            raise HarnessError(f"템플릿 파일이 없다: {original}")
        text, source = render(original.read_text(encoding="utf-8"), build_context(config), source=rel), f"키트 {rel}"
    spec = template_spec(text)
    if not spec["headings"]:
        raise HarnessError(f"{source}: 템플릿에 `## ` 절이 없다")
    spec[key] = numbered_heading(spec, number, source)
    tables = section_tables(spec.pop("sections")[spec[key]])
    if not tables:
        raise HarnessError(f"{source}: 템플릿 {number}장에 표가 없다")
    header, rows = tables[0]
    spec[f"{key}_header"] = header
    if key == "measurement":
        spec["measurement_rows"] = [row[0] for row in rows if row and row[0]]
    spec["source"] = source
    return spec


def plan_key_pattern(config: dict) -> re.Pattern:
    """플랜 파일 키: github은 이슈 번호, jira는 `<issue_prefix>-<번호>`(대소문자 무시)."""
    if config["tracker"] == "jira":
        return re.compile(re.escape(config.get("issue_prefix", "")) + r"-\d+", re.IGNORECASE)
    return re.compile(r"\d+")


def classify_plan_files(names: list[str], config: dict, key: str | None) -> dict[str, list[str]]:
    """D-15: `<키>.md` 플랜, `<키>-review*.md` 리뷰, `-mapping`·`-self-review` 제외, 그 밖은 무시."""
    key_pattern = re.escape(key) if key is not None else plan_key_pattern(config).pattern
    pattern = re.compile(rf"({key_pattern})(-review.*)?\.md", re.IGNORECASE if config["tracker"] == "jira" else 0)
    groups: dict[str, list[str]] = {"plan": [], "review": [], "excluded": [], "ignored": []}
    for name in sorted(names):
        stem = name[:-3] if name.endswith(".md") else name
        match = pattern.fullmatch(name)
        if name.endswith(".md") and (stem.endswith("-mapping") or "-self-review" in stem):
            if key is None or stem.lower().startswith(f"{key.lower()}-"):
                groups["excluded"].append(name)
        elif match:
            groups["review" if match.group(2) else "plan"].append(name)
        elif key is None:
            groups["ignored"].append(name)
    # 엄격 단계의 `-review.md`는 A·B 결과의 합집합 대조표다(영역 AGENTS.md 4장). 리뷰 양식이 아니므로 제외한다
    lowered = {name.lower() for name in names}
    combined = [name for name in groups["review"] if name.lower().endswith("-review.md") and
                {name[:-3].lower() + "-a.md", name[:-3].lower() + "-b.md"} & lowered]
    groups["review"] = [name for name in groups["review"] if name not in combined]
    groups["excluded"].extend(combined)
    return groups


def cmd_lint_plans(args) -> int:
    if args.self:
        target = KIT_ROOT
    else:
        target = Path(args.target).resolve() if args.target else Path.cwd()
    if args.key is not None and not LINT_KEY.fullmatch(args.key):
        raise HarnessError(f"키는 영문·숫자·`.`·`_`·`-`만 쓴다: {args.key!r}")
    config = load_config(target / CONFIG_NAME)
    if args.key is not None and not plan_key_pattern(config).fullmatch(args.key):
        raise HarnessError(f"키는 {config['tracker']} 이슈 키 형식이어야 한다(예: {build_context(config)['branch_key_example']}): "
                           f"{args.key!r}")
    plans_dir = target / "plans"
    names = [p.name for p in plans_dir.iterdir() if p.is_file()] if plans_dir.is_dir() else []
    groups = classify_plan_files(names, config, args.key)
    if args.key is not None and not groups["plan"] and not groups["review"]:
        raise HarnessError(f"plans/ 에 키 {args.key} 의 플랜·리뷰 파일이 없다: {plans_dir}")
    if not groups["plan"] and not groups["review"]:
        print(f"검사할 파일 없음: {plans_dir}")
        return 0
    specs = {}
    if groups["plan"]:
        specs["plan"] = load_lint_spec(target, config, PLAN_TEMPLATE, "3", "acceptance")
    if groups["review"]:
        specs["review"] = load_lint_spec(target, config, REVIEW_TEMPLATE, "6", "measurement")
    total_failures = total_warnings = 0
    for kind, label in (("plan", "플랜"), ("review", "리뷰")):
        for name in groups[kind]:
            try:
                text = (plans_dir / name).read_bytes().decode("utf-8-sig")
            except (OSError, UnicodeDecodeError) as exc:
                raise HarnessError(f"plans/{name} 을 UTF-8로 읽을 수 없다: {exc}") from exc
            failures, warnings = lint_document(text, specs[kind], kind)
            total_failures += len(failures)
            total_warnings += len(warnings)
            status = "실패" if failures else ("경고" if warnings else "통과")
            print(f"{status}: plans/{name} ({label})")
            for message in failures:
                print(f"  실패: {message}")
            for message in warnings:
                print(f"  경고: {message}")
    if groups["excluded"]:
        print(f"제외(-mapping·-self-review·엄격 합본 -review.md): {', '.join(groups['excluded'])}")
    if groups["ignored"]:
        print(f"무시(플랜·리뷰 이름 아님): {', '.join(groups['ignored'])}")
    sources = ", ".join(f"{spec['source']}" for spec in specs.values())
    print(f"파일 {len(groups['plan']) + len(groups['review'])}개, 실패 {total_failures}건, 경고 {total_warnings}건 "
          f"(템플릿: {sources})")
    return 1 if total_failures else 0


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

    judge = sub.add_parser("judge", help="변경 파일로 경량·표준·엄격을 판정한다")
    judge.add_argument("target", nargs="?", help="대상 저장소(기본 현재 디렉터리)")
    judge.add_argument("--self", action="store_true")
    source = judge.add_mutually_exclusive_group()
    source.add_argument("--base", help="비교 기준 ref(기본 origin/<default_branch>). merge-base 이후 변경과 작업 트리를 본다")
    source.add_argument("--files", help="변경 파일 목록(줄 단위). - 이면 표준 입력")
    judge.add_argument("--json", action="store_true", help="JSON으로 출력")
    judge.set_defaults(func=cmd_judge)

    classify = sub.add_parser("classify-ci", help="실패한 CI job의 원인을 분류해 JSONL로 쓴다")
    classify.add_argument("--jobs", required=True, help="job 메타데이터 JSON(GitLab job API 형태, 목록 또는 객체)")
    classify.add_argument("--trace-dir", help="job trace 디렉터리(<job_id>.log). 없으면 메타데이터만으로 분류")
    classify.add_argument("--out", help="JSONL 출력 파일. 생략하면 표준 출력")
    classify.set_defaults(func=cmd_classify_ci)

    lint_plans = sub.add_parser("lint-plans", help="plans/의 플랜·리뷰 파일을 템플릿 기준으로 검사한다")
    lint_plans.add_argument("key", nargs="?", help="이 키의 플랜·리뷰만 검사(생략하면 plans/ 전체)")
    lint_target = lint_plans.add_mutually_exclusive_group()
    lint_target.add_argument("--target", help="대상 저장소(기본 현재 디렉터리)")
    lint_target.add_argument("--self", action="store_true", help="키트 저장소 자신")
    lint_plans.set_defaults(func=cmd_lint_plans)

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
