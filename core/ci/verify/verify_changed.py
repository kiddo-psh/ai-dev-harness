#!/usr/bin/env python3
"""MR 변경 영역의 검증 명령을 CI에서 실행한다(#100). 표준 라이브러리만 쓴다.

종료 검증 hook(stop-verify)과 같은 선택(`harness_common.commands_for`)을 쓴다: 변경 파일이 속한 영역의
`areas[].verify`, 영역 밖 변경이면 `hooks.stop_verify`. hooks가 없는 도구(Codex 등)로 만든 MR도 같은 검증을 거친다.

    python verify_changed.py --base <ref> [--project .] [--common .claude/hooks/harness_common.py]

변경 파일은 `<base>`와 HEAD의 merge-base 이후 커밋이다(작업 트리는 보지 않는다).
실행할 명령이 있으면 먼저 Node 버전 선언과 실행 중인 node가 서로 맞는지 본다(#152). 어긋나면 명령을 실행하지 않고
실패한다. `HARNESS_VERIFY_PARITY=off`면 이 검사를 건너뛴다.
종료 코드: 모두 통과 0(실행할 명령이 없어도 0), 하나라도 실패 1, 입력·설정·git 오류 2.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
DEFAULT_COMMON = ".claude/hooks/harness_common.py"
PARITY_ENV = "HARNESS_VERIFY_PARITY"
_VERSION = r"(\d+(?:\.\d+){0,2})"
_DOCKER_NODE = re.compile(r"^\s*FROM\s+(?:--\S+\s+)*(?:\S+/)?node:" + _VERSION + r"(?![\d.])", re.IGNORECASE)
_CI_NODE = re.compile(r"(?:^|[\s\"'/])node:" + _VERSION + r"(?=$|[-@\s\"'])")


class VerifyError(Exception):
    """입력·설정·git 오류(종료 2)."""


def load_common(path: Path):
    if not path.is_file():
        raise VerifyError(f"{path} 이 없다. `harness init`으로 생성한다.")
    spec = importlib.util.spec_from_file_location("harness_common_for_verify", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - 복사본이 깨졌으면 원인을 보이고 종료 2(#100 리뷰 B F3)
        raise VerifyError(f"{path} 을 읽을 수 없다: {exc}") from exc
    for name in ("commands_for", "load_config", "git_result"):
        if not hasattr(module, name):
            raise VerifyError(f"{path} 에 {name} 이 없다. 키트 버전을 맞춘다(`harness init --force`).")
    return module


def changed_files(common, project: Path, base: str) -> list[str]:
    if base.startswith("-"):
        raise VerifyError(f"기준 ref가 잘못됐다: {base}")
    merge_base, err = common.git_result(project, "merge-base", base, "HEAD")
    if merge_base is None:
        raise VerifyError(f"기준 {base}와 HEAD의 merge-base를 구할 수 없다(얕은 clone이면 GIT_DEPTH=0): {err}")
    out, err = common.git_result(project, "-c", "core.quotepath=off", "diff", "--name-only", "--no-renames",
                                 "--relative", "-z", merge_base.strip(), "HEAD", "--")
    if out is None:
        raise VerifyError(f"git diff 실패: {err}")
    return [path for path in out.split("\0") if path]


def parse_version(text: str) -> tuple[int, ...] | None:
    """`22`, `v22.22.0`, `20.19` 같은 숫자 버전. `lts/*`·`$NODE_VERSION`처럼 숫자가 아니면 None."""
    match = re.fullmatch(r"v?" + _VERSION, text.strip())
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def _fmt(version: tuple[int, ...]) -> str:
    return ".".join(map(str, version))


def _pad(version: tuple[int, ...], fill: int = 0) -> tuple[int, ...]:
    return tuple(version) + (fill,) * (3 - len(version))


def _next(version: tuple[int, ...]) -> tuple[int, ...]:
    """부분 버전이 덮는 X-범위의 배타적 상한(22 → 23.0.0, 20.19 → 20.20.0)."""
    if len(version) == 1:
        return (version[0] + 1, 0, 0)
    return (version[0], version[1] + 1, 0)


def _comparators(op: str, version: tuple[int, ...]) -> list[tuple[str, tuple[int, ...]]]:
    full = len(version) == 3
    low = _pad(version)
    if op in ("", "="):
        return [(">=", low), ("<=", low)] if full else [(">=", low), ("<", _next(version))]
    if op == ">=":
        return [(">=", low)]
    if op == ">":
        return [(">", low)] if full else [(">=", _next(version))]
    if op == "<":
        return [("<", low)]
    if op == "<=":
        return [("<=", low)] if full else [("<", _next(version))]
    if op == "~":
        return [(">=", low), ("<", _next(version[:2] if len(version) > 1 else version))]
    # ^: 왼쪽에서 처음 0이 아닌 자리까지 고정한다(npm semver)
    if version[0] > 0 or len(version) == 1:
        upper = (version[0] + 1, 0, 0)
    elif len(version) == 2 or version[1] > 0:
        upper = (0, version[1] + 1, 0)
    else:
        upper = (0, 0, version[2] + 1)
    return [(">=", low), ("<", upper)]


_TOKEN = re.compile(r"(<=|>=|<|>|=|\^|~)?v?(\*|[xX]|\d+(?:\.(?:\d+|[xX*])){0,2})")


def _partial(text: str) -> tuple[int, ...]:
    """`1.x`·`*`의 와일드카드 앞까지만 숫자로 둔다."""
    parts = []
    for part in text.split("."):
        if not part.isdigit():
            break
        parts.append(int(part))
    return tuple(parts)


def parse_range(text: str) -> list[list[tuple[str, tuple[int, ...]]]]:
    """npm `engines` 범위의 부분집합(`>= > <= < = ^ ~ x * ||`, 하이픈 범위, 공백 AND). 모르는 모양이면 ValueError."""
    alternatives = []
    for alt in text.split("||"):
        alt = alt.strip()
        hyphen = re.fullmatch(r"v?(\S+)\s+-\s+v?(\S+)", alt)
        if hyphen:
            low, high = _partial(hyphen.group(1)), _partial(hyphen.group(2))
            if not low or not high:
                raise ValueError(text)
            alternatives.append([(">=", _pad(low))] + _comparators("<=", high))
            continue
        comparators = []
        for token in re.sub(r"(<=|>=|<|>|=|\^|~)\s+", r"\1", alt).split():
            match = _TOKEN.fullmatch(token)
            if not match:
                raise ValueError(text)
            version = _partial(match.group(2))
            if version:  # `*`·`x`는 아무 버전이나 허용한다
                comparators += _comparators(match.group(1) or "", version)
        alternatives.append(comparators)
    return alternatives


def satisfies(version: tuple[int, ...], alternatives) -> bool:
    version = _pad(version)
    checks = {">=": lambda b: version >= b, ">": lambda b: version > b,
              "<": lambda b: version < b, "<=": lambda b: version <= b}
    return any(all(checks[op](bound) for op, bound in alt) for alt in alternatives)


def _bump(version: tuple[int, ...]) -> tuple[int, ...]:
    return version[:2] + (version[2] + 1,)


def _intersects(low: tuple[int, ...], high: tuple[int, ...], alternatives) -> bool:
    """[low, high) 구간에 범위를 만족하는 버전이 하나라도 있는가. 버전이 정수라 `> b`는 `>= b+패치1`, `<= b`는 `< b+패치1`이다."""
    for alt in alternatives:
        lower, upper = low, high
        for op, bound in alt:
            if op in (">=", ">"):
                lower = max(lower, bound if op == ">=" else _bump(bound))
            else:
                upper = min(upper, bound if op == "<" else _bump(bound))
        if lower < upper:
            return True
    return False


def _could_satisfy(version: tuple[int, ...], alternatives) -> bool:
    """부분 버전(`node:22`)은 그 버전이 덮는 구간(22.0.0 이상 23.0.0 미만)과 범위가 겹치면 맞는 것으로 본다(#154 Codex)."""
    high = _bump(version) if len(version) == 3 else _next(version)
    return _intersects(_pad(version), high, alternatives)


def _agree(a: tuple[int, ...], b: tuple[int, ...]) -> bool:
    """공통 자릿수까지 같으면 같은 버전으로 본다(`22`와 `22.22.0`). 패치 자리는 비교하지 않는다."""
    size = min(len(a), len(b), 2)
    return a[:size] == b[:size]


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None
    except OSError:
        return None


def node_declarations(project: Path, config: dict):
    """루트와 `areas[].dir`의 Node 버전 선언. (고정 버전 [(출처, 버전)], engines [(출처, 범위)], 경고)."""
    pins, engines, warnings = [], [], []
    for area in [""] + sorted({area["dir"] for area in config.get("areas", [])}):
        base = project / area if area else project

        def label(name: str) -> str:
            return f"{area}/{name}" if area else name

        for name in (".nvmrc", ".node-version"):
            text = _read(base / name)
            lines = [line.strip() for line in (text or "").splitlines() if line.strip() and not line.strip().startswith("#")]
            version = parse_version(lines[0]) if lines else None
            if version:
                pins.append((label(name), version))
        for line in (_read(base / ".tool-versions") or "").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] in ("nodejs", "node") and parse_version(parts[1]):
                pins.append((label(".tool-versions"), parse_version(parts[1])))
        for path in sorted(base.glob("*Dockerfile*")):
            for number, line in enumerate((_read(path) or "").splitlines(), 1):
                match = _DOCKER_NODE.match(line)
                if match:
                    pins.append((f"{label(path.name)}:{number}", parse_version(match.group(1))))
        text = _read(base / "package.json")
        if text is not None:
            try:
                data = json.loads(text)
            except ValueError:
                warnings.append(f"{label('package.json')}을 JSON으로 읽지 못해 engines.node를 건너뛴다")
                data = None
            node = data.get("engines", {}).get("node") if isinstance(data, dict) and isinstance(
                data.get("engines"), dict) else None
            if isinstance(node, str) and node.strip():
                engines.append((label("package.json"), node.strip()))
    for number, line in enumerate((_read(project / ".gitlab-ci.yml") or "").splitlines(), 1):
        if not line.lstrip().startswith("#"):
            for match in _CI_NODE.finditer(line):
                pins.append((f".gitlab-ci.yml:{number}", parse_version(match.group(1))))
    return pins, engines, warnings


def detect_node() -> tuple[int, ...] | None:
    node = shutil.which("node")
    if not node:
        return None
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_version(out.strip())


_DETECT = object()


def node_parity(project: Path, config: dict, runtime=_DETECT) -> tuple[list[str], list[str]]:
    """Node 버전 선언끼리, 그리고 실행 중인 node와 맞는지 본다(#152). (실패 사유, 경고)."""
    pins, engines, warnings = node_declarations(project, config)
    if not pins and not engines:
        return [], warnings
    problems = []
    listed = ", ".join(f"{source} {_fmt(version)}" for source, version in pins)
    if any(not _agree(a, b) for i, (_, a) in enumerate(pins) for _, b in pins[i + 1:]):
        problems.append(f"고정 버전이 서로 다르다: {listed}")
    majors = sorted({version[0] for _, version in pins})
    ranges = []
    for source, text in engines:
        try:
            alternatives = parse_range(text)
        except ValueError:
            warnings.append(f"{source}의 engines.node `{text}`를 해석하지 못해 범위 검사를 건너뛴다")
            continue
        ranges.append((source, text, alternatives))
        outside = [f"{s} {_fmt(v)}" for s, v in pins if not _could_satisfy(v, alternatives)]
        if outside:
            problems.append(f"{source}의 engines.node `{text}` 밖의 고정 버전: {', '.join(outside)}")
        extra = [m for m in range(100) if majors and m not in majors
                 and _intersects((m, 0, 0), (m + 1, 0, 0), alternatives)]
        if extra:
            shown = ", ".join(map(str, extra[:3])) + (" 등" if len(extra) > 3 else "")
            problems.append(f"{source}의 engines.node `{text}`가 고정 버전의 메이저({', '.join(map(str, majors))}) 밖의 "
                            f"Node {shown}도 허용한다. 로컬 node가 다른 메이저여도 막히지 않아 로컬 통과·CI 실패가 난다. "
                            f"상한을 둔다(예: 범위 끝에 ` <{majors[-1] + 1}`)")
    if runtime is _DETECT:
        runtime = detect_node()
    if runtime:
        label = f"실행 중인 node {_fmt(runtime)}"
        off = [f"{s} {_fmt(v)}" for s, v in pins if not _agree(v, runtime)]
        if off:
            problems.append(f"{label}가 고정 버전과 다르다: {', '.join(off)}")
        for source, text, alternatives in ranges:
            if not satisfies(runtime, alternatives):
                problems.append(f"{label}가 {source}의 engines.node `{text}` 밖이다")
    return problems, warnings


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MR 변경 영역의 검증 명령을 실행한다")
    parser.add_argument("--base", required=True, help="대상 브랜치 ref(예: origin/main)")
    parser.add_argument("--project", default=".", help="저장소 루트(기본 현재 디렉터리)")
    parser.add_argument("--common", help=f"harness_common.py 경로(기본 <project>/{DEFAULT_COMMON})")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # Windows 파이프에서도 한국어·명령 문자열을 깨지지 않게
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    project = Path(args.project).resolve()
    try:
        common = load_common(Path(args.common) if args.common else project / DEFAULT_COMMON)
        try:
            config = common.load_config(project)
        except common.ConfigError as exc:
            raise VerifyError(str(exc)) from exc
        files = changed_files(common, project, args.base)
    except VerifyError as exc:
        print(f"harness verify: {exc}", file=sys.stderr)
        return 2
    commands = common.commands_for(config, files)
    bash = common.verify_shell() if hasattr(common, "verify_shell") else None
    print(f"harness verify: 변경 파일 {len(files)}개, 실행할 검증 명령 {len(commands)}개")
    if commands and os.environ.get(PARITY_ENV, "").strip().lower() != "off":
        problems, warnings = node_parity(project, config)
        for warning in warnings:
            print(f"harness verify: 경고: {warning}", file=sys.stderr)
        if problems:
            for problem in problems:
                print(f"harness verify: Node 버전: {problem}", file=sys.stderr)
            print(f"harness verify: 선언을 맞춘 뒤 다시 돌린다. 이 검사만 끄려면 {PARITY_ENV}=off", file=sys.stderr)
            return 1
    failed = []
    for cmd in commands:
        print(f"$ {cmd}", flush=True)
        args, shell, env = common.shell_command(cmd, bash) if bash else (cmd, True, None)
        if subprocess.run(args, shell=shell, cwd=project, env=env).returncode != 0:
            failed.append(cmd)
    for cmd in failed:
        print(f"harness verify: 실패: {cmd}", file=sys.stderr)
    if failed and os.name == "nt" and bash is None and hasattr(common, "NO_BASH_HINT"):  # #115 리뷰 A F2
        print(f"harness verify: {common.NO_BASH_HINT}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
