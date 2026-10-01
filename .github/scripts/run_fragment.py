"""GitLab CI 보안 검사 조각을 GitHub Actions PR에서 같은 이미지·스크립트로 실행한다(ADR-0003, M1-7).

검사를 두 벌 쓰면 정책이 갈라지므로 `core/ci/gitlab/<name>.yml`에서 이미지, job 변수, 스크립트,
경고로 허용하는 종료 코드(`allow_failure: exit_codes`)를 꺼내 `docker run`으로 실행한다.
GitLab MR 변수는 PR merge 커밋에서 만든다(merged results 파이프라인과 같은 모양).
셸은 GitLab Docker executor와 같게 bash가 있으면 `set -eo pipefail`의 bash, 없으면 sh다.

조각 형식은 좁게 받는다. 최상위 job 키 하나, 두 칸 들여쓰기의 알려진 키, `script:` 아래 `- |` 블록 하나.
이 러너가 판정을 내리므로 모르는 모양은 추측하지 않고 실패한다. 스크립트 일부를 빼고 돌려 통과로 끝내지 않는다.

사용법: python .github/scripts/run_fragment.py <조각 이름> [저장소 경로]
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
GITLAB = ROOT / "core" / "ci" / "gitlab"
PROJECT_DIR = "/builds/project"  # 컨테이너 안 저장소 경로(CI_PROJECT_DIR)
SCRIPT_INDENT = 6
PASS_THROUGH = re.compile(r"^(HARNESS_|TRIVY_)[A-Z0-9_]*$")  # 소비자가 주는 조각 변수는 그대로 넘긴다
SCALAR_KEYS = {"stage", "interruptible"}
BLOCK_KEYS = {"image", "variables", "cache", "rules", "allow_failure", "script", "artifacts"}
REQUIRED_KEYS = {"image", "rules", "script"}
# 이 경로를 바꾼 PR은 검사 자체를 바꿀 수 있다. 실패로 막지는 않고(정당한 변경도 같은 경로다) 경고로 드러낸다.
SELF_PATHS = [".github/workflows/", ".github/scripts/", "core/ci/gitlab/"]
# GitLab Docker executor처럼 bash가 있으면 bash에 pipefail을 건다. 스크립트는 $1로 넘긴다
SHELL_WRAPPER = ('if command -v bash >/dev/null 2>&1; then exec bash -eo pipefail -c "$1"; fi; '
                 'exec sh -e -c "$1"')


class FragmentError(Exception):
    pass


def split_job(lines: list[str], source: str) -> dict[str, tuple[str, list[str]]]:
    """job 본문을 {키: (같은 줄 값, 하위 줄)}로 나눈다. 모르는 키와 들여쓰기는 실패한다."""
    sections: dict[str, tuple[str, list[str]]] = {}
    current = None
    for line in lines:
        if not line.strip():
            if current:
                sections[current][1].append("")
            continue
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise FragmentError(f"{source}: 들여쓰기에 탭이 있다: {line.strip()}")
        key = re.match(r"^  ([a-z_]+):(.*)$", line)
        if key:
            name, rest = key.group(1), key.group(2).strip()
            if name not in SCALAR_KEYS | BLOCK_KEYS:
                raise FragmentError(f"{source}: 러너가 모르는 job 키다: {name}")
            if name in sections:
                raise FragmentError(f"{source}: {name}가 두 번 있다")
            if (name in SCALAR_KEYS) != bool(rest):
                raise FragmentError(f"{source}: {name}의 형식이 다르다: {line.strip()}")
            sections[name] = (rest, [])
            current = name
        elif line.startswith("    ") and current:
            sections[current][1].append(line.rstrip())
        else:
            raise FragmentError(f"{source}: job 본문에서 읽지 못한 줄(들여쓰기 4칸 미만): {line.strip()}")
    for _, children in sections.values():
        while children and not children[-1]:
            children.pop()
    missing = REQUIRED_KEYS - sections.keys()
    if missing:
        raise FragmentError(f"{source}: 필수 키가 없다: {', '.join(sorted(missing))}")
    return sections


def parse_fragment(text: str, source: str = "<fragment>") -> dict:
    """{job, image, variables, allow_codes, script}."""
    lines = text.splitlines()
    if "\r" in text:
        raise FragmentError(f"{source}: 줄 끝이 LF가 아니다")
    tops = [i for i, line in enumerate(lines) if line and not line[0].isspace() and not line.startswith("#")]
    if len(tops) != 1 or not re.fullmatch(r"[a-z][a-z0-9-]*:", lines[tops[0]]):
        raise FragmentError(f"{source}: 최상위 job이 하나여야 한다(찾은 줄 {len(tops)}개)")
    job = lines[tops[0]][:-1]
    sections = split_job(lines[tops[0] + 1:], source)

    image = None
    for line in sections["image"][1]:
        m = re.fullmatch(r"    name: (\S+)", line)
        if m and image is None:
            image = m.group(1)
        elif line != '    entrypoint: [""]':
            raise FragmentError(f"{source}: image에서 읽지 못한 줄: {line.strip()}")
    if image is None:
        raise FragmentError(f"{source}: image.name이 없다")

    variables = {}
    for line in sections.get("variables", ("", []))[1]:
        if not line or line.lstrip().startswith("#"):
            continue
        m = re.fullmatch(r'    ([A-Z_][A-Z0-9_]*): (?:"([^"$\\]*)"|([^\s"\'$#\\]+))', line)
        if not m:
            raise FragmentError(f"{source}: 읽지 못한 변수 줄(따옴표·$·주석은 받지 않는다): {line.strip()}")
        variables[m.group(1)] = m.group(2) if m.group(2) is not None else m.group(3)

    allow_codes: set[int] = set()
    if "allow_failure" in sections:
        allow = sections["allow_failure"][1]
        m = re.fullmatch(r"    exit_codes: \[(\d+(?:, *\d+)*)\]", allow[0]) if len(allow) == 1 else None
        if not m:
            raise FragmentError(f"{source}: allow_failure는 exit_codes 목록만 지원한다")
        allow_codes = {int(code) for code in m.group(1).split(",")}

    script_lines = sections["script"][1]
    if not script_lines or script_lines[0] != "    - |":
        raise FragmentError(f"{source}: script는 `- |` 블록 하나여야 한다")
    block = []
    for line in script_lines[1:]:
        if line and not line.startswith(" " * SCRIPT_INDENT):
            raise FragmentError(f"{source}: script 블록이 하나가 아니다: {line.strip()}")
        block.append(line[SCRIPT_INDENT:])
    script = "\n".join(block).strip("\n") + "\n"
    if not script.startswith("set -eu"):
        raise FragmentError(f"{source}: 스크립트가 `set -eu`로 시작하지 않는다")
    return {"job": job, "image": image, "variables": variables, "allow_codes": allow_codes, "script": script}


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise FragmentError(f"git {' '.join(args)} 실패: {result.stderr.strip() or result.returncode}")
    return result.stdout.strip()


def event_head_sha() -> str | None:
    """GitHub Actions면 이벤트의 PR head 커밋. 밖에서 돌리면(로컬 검증) None."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return None
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        return event["pull_request"]["head"]["sha"]
    except (KeyError, OSError, ValueError, TypeError) as exc:
        raise FragmentError(f"pull_request 이벤트의 head 커밋을 읽지 못했다: {exc}") from exc


def gitlab_env(repo: Path) -> dict:
    """PR merge 커밋(HEAD)에서 GitLab MR 변수를 만든다. 첫 부모는 대상 브랜치, 둘째 부모는 PR head."""
    if git(repo, "rev-parse", "--is-shallow-repository") != "false":
        raise FragmentError("얕은 clone이다. actions/checkout에 fetch-depth: 0을 준다")
    partial = subprocess.run(["git", "-C", str(repo), "config", "--get", "extensions.partialclone"],
                             capture_output=True, text=True)
    if partial.stdout.strip():  # blob이 없으면 gitleaks가 0개 커밋을 검사하고 통과한다
        raise FragmentError("partial clone이다. checkout에 filter를 주지 않는다")
    parents = git(repo, "rev-list", "--parents", "-n", "1", "HEAD").split()
    if len(parents) != 3:
        raise FragmentError("HEAD가 PR merge 커밋이 아니다(부모 2개). pull_request 이벤트와 fetch-depth: 0인지 확인한다")
    head, target, source = parents
    expected = event_head_sha()
    if expected is not None and source != expected:
        raise FragmentError(f"merge 커밋의 둘째 부모 {source[:12]}가 PR head {expected[:12]}와 다르다. checkout ref를 확인한다")
    return {
        "CI_PIPELINE_SOURCE": "merge_request_event",
        "CI_PROJECT_DIR": PROJECT_DIR,
        "CI_COMMIT_SHA": head,
        "CI_MERGE_REQUEST_TARGET_BRANCH_SHA": target,
        "CI_MERGE_REQUEST_SOURCE_BRANCH_SHA": source,
        "CI_MERGE_REQUEST_DIFF_BASE_SHA": git(repo, "merge-base", target, source),
    }


def self_changes(repo: Path, env: dict) -> list[str]:
    """이 PR이 검사 정의(workflow·러너·조각)를 바꿨으면 그 파일 목록."""
    out = git(repo, "diff", "--name-only", env["CI_MERGE_REQUEST_DIFF_BASE_SHA"],
              env["CI_MERGE_REQUEST_SOURCE_BRANCH_SHA"], "--", *SELF_PATHS)
    return out.splitlines() if out else []


def outcome(code: int, allow_codes: set[int], job: str) -> int:
    """조각이 경고로 허용한 종료 코드만 0으로 바꾸고 GitHub 경고 주석을 남긴다."""
    if code != 0 and code in allow_codes:
        print(f"::warning title={job}::경고 단계 발견(종료 코드 {code}). 위 로그를 확인한다.")
        return 0
    return code


def docker_command(frag: dict, repo: Path, env: dict) -> list[str]:
    cmd = ["docker", "run", "--rm", "-v", f"{repo}:{PROJECT_DIR}", "-w", PROJECT_DIR, "--entrypoint", "sh"]
    for key in sorted(env):
        cmd += ["-e", key]  # 값은 프로세스 환경으로 넘겨 명령줄에 남기지 않는다
    return cmd + [frag["image"], "-c", SHELL_WRAPPER, "harness-runner", frag["script"]]


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    name = argv[1]
    repo = Path(argv[2] if len(argv) == 3 else os.getcwd()).resolve()
    path = GITLAB / f"{name}.yml"
    try:
        if not re.fullmatch(r"[a-z-]+", name) or not path.is_file():
            raise FragmentError(f"조각이 없다: {path}")
        frag = parse_fragment(path.read_text(encoding="utf-8"), path.name)
        mr = gitlab_env(repo)
        changed = self_changes(repo, mr)
    except FragmentError as exc:
        print(f"harness: {exc}", file=sys.stderr)
        return 2
    passed = {k: v for k, v in os.environ.items() if PASS_THROUGH.match(k)}
    env = {**frag["variables"], **passed, **mr}  # MR 범위 변수는 러너 환경으로 덮을 수 없다
    if changed:
        print(f"::warning title={frag['job']}::이 PR이 검사 정의를 바꿨다. 이 결과만으로 판단하지 않고 사람이 리뷰한다: "
              + ", ".join(changed))
    print(f"harness: {frag['job']} ({frag['image']})")
    print(f"harness: 범위 {mr['CI_MERGE_REQUEST_DIFF_BASE_SHA'][:12]}..{mr['CI_MERGE_REQUEST_SOURCE_BRANCH_SHA'][:12]}"
          f" (대상 {mr['CI_MERGE_REQUEST_TARGET_BRANCH_SHA'][:12]})")
    sys.stdout.flush()
    code = subprocess.run(docker_command(frag, repo, env), env={**os.environ, **env}).returncode
    return outcome(code, frag["allow_codes"], frag["job"])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
