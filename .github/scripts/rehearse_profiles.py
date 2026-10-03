"""프로필별 리허설(M3-5): fixture 저장소에 프로필을 적용하고 생성 → 컨벤션 테스트 → 빌드를 실제로 돌린다.

프로필마다 `tests/fixtures/profiles/<name>/`(소비자 저장소 모양)를 임시 디렉터리로 복사한 뒤 다음을 한다.

1. `harness init`(루트)와 `init --area <dir> --profile <name>`
2. `harness scaffold`. 출력된 조각은 fixture에 미리 둔 표식(`rehearsal:...`) 자리에 붙인다(라우터·내비게이션 그래프)
3. 준비: Gradle wrapper 생성(fixture에 wrapper jar를 두지 않는다. PATH의 고정 버전 Gradle로 만든다), `npm ci`
4. 프로필 README의 생성 뒤 형식 맞춤(spotlessApply·ktlintFormat)
5. 영역 `verify` 명령을 `stop-verify`처럼 저장소 루트에서 셸로 실행한다. 모두 통과해야 한다
6. `harness check`로 컨벤션 파일 드리프트가 없는지 본다(형식 도구가 생성 파일을 바꾸면 여기서 드러난다)
7. 음성 시나리오: 규칙 위반 파일을 넣고 같은 검증 명령을 실행한다. 실패(0이 아닌 종료 코드)이면서 출력에
   규칙·테스트를 가리키는 문자열이 있어야 통과다. 도구 오류로 실패한 것을 기대대로 실패한 것으로 읽지 않기 위해서다

무거운 빌드는 CI `profiles` job에서만 돈다. 키트 단위 테스트는 준비 단계(`prepare`)만 본다.

사용법: python .github/scripts/rehearse_profiles.py spring-java|react-ts|android-kotlin [--keep]
"""

import difflib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HARNESS = ROOT / "bin" / "harness.py"
FIXTURES = ROOT / "tests" / "fixtures" / "profiles"
# CI(setup-gradle의 gradle-version)와 같은 값이다. wrapper를 이 버전으로 만든다
GRADLE_VERSION = "8.14.3"
# wrapper가 내려받는 배포본 검증용(https://services.gradle.org/distributions/gradle-8.14.3-bin.zip.sha256)
GRADLE_DISTRIBUTION_SHA256 = "bd71102213493060956ec229d946beee57158dbd89d0e62b91bca0fa2c5f3531"
SNIPPET_HEADER = "공유 파일에 직접 붙일 코드 조각:"


class RehearsalError(Exception):
    pass


# ---------------------------------------------------------------------------
# 시나리오
# ---------------------------------------------------------------------------

SPRING_LEAK_CONTROLLER = """\
package com.example.rehearsal.domain.moviereview.controller;

import com.example.rehearsal.domain.moviereview.repository.MovieReviewRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

// 음성 시나리오: controller가 service를 거치지 않고 repository를 부른다(계층 규칙 위반)
@RestController
@RequiredArgsConstructor
public class MovieReviewCountController {

    private final MovieReviewRepository movieReviewRepository;

    @GetMapping("/api/v1/movie-review-count")
    public long count() {
        return movieReviewRepository.count();
    }
}
"""

REACT_MOCKS_PAGE = """\
import { movies } from '../../mocks/movies';

// 음성 시나리오: 화면이 mocks/를 직접 import한다(no-mocks-import)
export default function LeakPage() {
  return <h1>{movies[0].title}</h1>;
}
"""

REACT_IMG_PAGE = """\
// 음성 시나리오: 대체 텍스트 없는 이미지(jsx-a11y/alt-text)
export default function PosterPage() {
  return <img src="/poster.png" />;
}
"""

ANDROID_RETROFIT_VIEWMODEL = """package com.example.rehearsal.feature.meal.ui.remote

import androidx.lifecycle.ViewModel
import retrofit2.Retrofit

// 음성 시나리오: ViewModel이 Repository 인터페이스를 거치지 않고 Retrofit을 직접 쓴다(viewmodel-repository-only, ADR-04).
// Retrofit은 :core가 api로 노출하므로 컴파일은 된다. 컨벤션 테스트(Konsist)가 막아야 한다
class MealRemoteViewModel(
    private val retrofit: Retrofit,
) : ViewModel() {
    fun baseUrl(): String = retrofit.baseUrl().toString()
}
"""

ANDROID_ROOM_ENTITY = """package com.example.rehearsal.feature.meal.data

import androidx.room.Entity
import androidx.room.PrimaryKey

// 음성 시나리오: feature 모듈이 Room을 쓴다(feature-no-room, ADR-03: Room은 :core의 Workout 테이블만).
// Room 런타임은 :core가 api로 노출하므로 컴파일은 된다(애너테이션 처리기는 없다)
@Entity
data class MealCacheEntity(
    @PrimaryKey val id: Long,
)
"""

ANDROID_IMAGE_LAYOUT = """\
<?xml version="1.0" encoding="utf-8"?>
<!-- 음성 시나리오: contentDescription 없는 이미지(Android Lint ContentDescription) -->
<ImageView xmlns:android="http://schemas.android.com/apk/res/android"
    android:layout_width="wrap_content"
    android:layout_height="wrap_content"
    android:src="@android:drawable/ic_menu_info_details" />
"""


def scenarios() -> dict[str, dict]:
    """프로필 이름 → 시나리오.

    areas: init --area 인자(dir, vars, profile — 생략하면 시나리오 이름의 프로필). scaffold: (영역, 종류, 이름, --var 목록). paste: 조각 붙이기 함수 이름.
    gradle_roots: wrapper를 만들 Gradle 빌드 루트. setup·format: 저장소 루트에서 실행할 셸 명령.
    negatives: name, files(저장소 기준 경로 → 내용), expect(출력에 있어야 할 문자열).
    """
    return {
        "spring-java": {
            "areas": [{"dir": "backend", "vars": {"base_package": "com.example.rehearsal"}}],
            "scaffold": [("backend", "domain", "MovieReview", [])],
            "paste": None,
            "gradle_roots": ["backend"],
            "setup": [],
            "format": ["cd backend && ./gradlew spotlessApply"],
            "negatives": [
                {"name": "controller-calls-repository",
                 "files": {"backend/src/main/java/com/example/rehearsal/domain/moviereview/controller/"
                           "MovieReviewCountController.java": SPRING_LEAK_CONTROLLER},
                 "expect": ["Architecture Violation", "MovieReviewCountController"]},
            ],
        },
        "react-ts": {
            "areas": [{"dir": "frontend", "vars": {}}],
            "scaffold": [("frontend", "screen", "MovieDetail", ["area=movies"]),
                         ("frontend", "api", "movie-review", [])],
            "paste": "paste_react",
            "gradle_roots": [],
            "setup": ["npm --prefix frontend ci --no-audit --no-fund"],
            "format": [],
            "negatives": [
                {"name": "page-imports-mocks",
                 "files": {"frontend/src/pages/LeakPage/index.tsx": REACT_MOCKS_PAGE},
                 "expect": ["[no-mocks-import]", "LeakPage"]},
                {"name": "img-without-alt",
                 "files": {"frontend/src/pages/PosterPage/index.tsx": REACT_IMG_PAGE},
                 "expect": ["jsx-a11y/alt-text", "PosterPage"]},
            ],
        },
        "android-kotlin": {
            # 냠냠코치 ADR-05 모듈 구성을 줄인 fixture. 영역은 규칙이 다른 단위 4개 + Konsist 전용 모듈(결정표 9장 Q3)
            "areas": [
                {"dir": "android/app", "vars": {"base_package": "com.example.rehearsal"}},
                {"dir": "android/core", "vars": {"base_package": "com.example.rehearsal.core", "module": "core"}},
                {"dir": "android/feature", "vars": {"base_package": "com.example.rehearsal", "module": "feature",
                                                    "gradle_tasks": ":feature:meal:check :feature:workout:check"}},
                {"dir": "android/wear", "vars": {"base_package": "com.example.rehearsal.wear", "module": "wear",
                                                 "min_sdk": "30"}},
                {"dir": "android/konsist-test", "profile": "android-konsist",
                 "vars": {"base_package": "com.example.rehearsal.konsist"}},
            ],
            "scaffold": [("android/feature", "screen", "MealSummary", ["feature=meal"]),
                         ("android/feature", "repository", "MealLog", ["feature=meal"]),
                         ("android/wear", "wear-screen", "HeartRate", [])],
            "paste": "paste_android",
            "gradle_roots": ["android"],
            "setup": [],
            "format": ["android/gradlew -p android :app:ktlintFormat :core:ktlintFormat :feature:meal:ktlintFormat "
                       ":feature:workout:ktlintFormat :wear:ktlintFormat :konsist-test:ktlintFormat"],
            "negatives": [
                {"name": "viewmodel-imports-retrofit",
                 "files": {"android/feature/meal/src/main/java/com/example/rehearsal/feature/meal/ui/remote/"
                           "MealRemoteViewModel.kt": ANDROID_RETROFIT_VIEWMODEL},
                 "expect": ["viewModelUsesRepositoryOnly", "MealRemoteViewModel"]},
                {"name": "feature-imports-room",
                 "files": {"android/feature/meal/src/main/java/com/example/rehearsal/feature/meal/data/"
                           "MealCacheEntity.kt": ANDROID_ROOM_ENTITY},
                 "expect": ["featureDoesNotUseRoom", "MealCacheEntity"]},
                {"name": "image-without-content-description",
                 "files": {"android/app/src/main/res/layout/negative_image.xml": ANDROID_IMAGE_LAYOUT},
                 "expect": ["[ContentDescription]", "negative_image.xml"]},
            ],
        },
    }


# ---------------------------------------------------------------------------
# 실행 도구
# ---------------------------------------------------------------------------


def child_env() -> dict:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def harness(*args: str) -> str:
    result = subprocess.run([sys.executable, str(HARNESS), *args], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", env=child_env())
    if result.returncode != 0:
        raise RehearsalError(f"harness {' '.join(args[:2])} 실패: {(result.stdout + result.stderr).strip()}")
    return result.stdout


def shell(cmd: str, cwd: Path) -> tuple[int, str]:
    """stop-verify처럼 셸 명령을 cwd에서 실행한다. 출력을 흘려 보내면서 모아 돌려준다(빌드가 길다)."""
    print(f"$ {cmd}", flush=True)
    proc = subprocess.Popen(cmd, shell=True, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, env=child_env())
    chunks = []
    for raw in proc.stdout:
        line = raw.decode("utf-8", errors="replace")
        chunks.append(line)
        print(line, end="", flush=True)
    return proc.wait(), "".join(chunks)


def remove_tree(path: Path) -> None:
    def writable_remove(func, name, _error):
        os.chmod(name, stat.S_IWRITE)
        func(name)
    if path.exists():
        shutil.rmtree(path, onerror=writable_remove)


def write(repo: Path, rel: str, content: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------
# 조각 붙이기
# ---------------------------------------------------------------------------


def snippet_of(output: str) -> str:
    if SNIPPET_HEADER not in output:
        raise RehearsalError(f"scaffold 출력에 붙일 조각이 없다: {output.strip()[:300]}")
    return output.split(SNIPPET_HEADER, 1)[1].strip("\n")


def insert_at_marker(path: Path, marker: str, lines: list[str]) -> None:
    """`// <marker>` 줄 앞에 같은 들여쓰기로 줄을 넣는다. 표식은 남긴다."""
    text = path.read_text(encoding="utf-8")
    out, found = [], False
    for line in text.splitlines(keepends=True):
        if line.strip() == f"// {marker}":
            indent = line[:len(line) - len(line.lstrip())]
            out.extend(f"{indent}{item}\n" if item.strip() else "\n" for item in lines)
            found = True
        out.append(line)
    if not found:
        raise RehearsalError(f"{path.name}에 표식 // {marker} 가 없다")
    path.write_text("".join(out), encoding="utf-8", newline="\n")


def add_imports(path: Path, imports: list[str]) -> None:
    """없는 import만 마지막 import 줄 뒤에 더한다. 순서는 형식 도구(ktlintFormat)가 맞춘다."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    present = {line.strip() for line in lines}
    new = [f"{item}\n" for item in imports if item not in present]
    last = max((i for i, line in enumerate(lines) if line.startswith("import ")), default=None)
    if last is None:
        raise RehearsalError(f"{path.name}에 import 줄이 없다")
    lines[last + 1:last + 1] = new
    path.write_text("".join(lines), encoding="utf-8", newline="\n")


def paste_react(repo: Path, snippets: list[tuple[str, str, str]]) -> None:
    """screen 조각 4덩어리(ROUTE_PATTERN, path, import, 라우트 객체)를 routes/의 표식 자리에 붙인다."""
    targets = [("routes/paths.ts", "rehearsal:route-pattern"), ("routes/paths.ts", "rehearsal:path"),
               ("routes/router.tsx", "rehearsal:import"), ("routes/router.tsx", "rehearsal:route")]
    for area, kind, snippet in snippets:
        if kind != "screen":
            continue
        blocks = [block for block in snippet.split("\n\n") if block.strip()]
        if len(blocks) != len(targets):
            raise RehearsalError(f"screen 조각 덩어리가 {len(blocks)}개다(기대 {len(targets)}): {snippet[:300]}")
        for block, (rel, marker) in zip(blocks, targets):
            lines = block.splitlines()
            if not lines[0].startswith("//") or rel not in lines[0]:
                raise RehearsalError(f"조각 설명이 {rel}을 가리키지 않는다: {lines[0]}")
            code = [line for line in lines if not line.startswith("//")]
            if marker == "rehearsal:import":
                code = [line.replace("//", "/") for line in code]  # area를 비우면 생기는 `//`(조각 설명대로 고친다)
            insert_at_marker(repo / area / "src" / rel, marker, code)


def paste_android(repo: Path, snippets: list[tuple[str, str, str]]) -> None:
    """composable 블록을 내비게이션 그래프 표식 자리에, 주석의 import를 같은 파일에 붙인다.

    feature 영역의 화면 조각은 :app의 그래프에 붙인다(ADR-05: 화면 간 이동은 :app이 맡는다).
    """
    hosts = {"screen": "android/app/src/main/java/com/example/rehearsal/RehearsalNavHost.kt",
             "wear-screen": "android/wear/src/main/java/com/example/rehearsal/wear/WearNavHost.kt"}
    for _area, kind, snippet in snippets:
        lines = snippet.splitlines()
        imports = [line[3:].strip() for line in lines if line.startswith("// import ")]
        code = [line for line in lines if not line.startswith("//")]
        if not imports or not code:
            raise RehearsalError(f"{kind} 조각에 import 주석이나 코드가 없다: {snippet[:300]}")
        host = repo / hosts[kind]
        insert_at_marker(host, "rehearsal:destinations", code)
        add_imports(host, imports)


PASTERS = {"paste_react": paste_react, "paste_android": paste_android}


# ---------------------------------------------------------------------------
# 리허설
# ---------------------------------------------------------------------------


def prepare(name: str, repo: Path) -> dict:
    """fixture 복사 → init(루트·영역) → scaffold → 조각 붙이기. 외부 도구를 쓰지 않는다(단위 테스트 대상)."""
    scenario = scenarios().get(name)
    if scenario is None:
        raise RehearsalError(f"모르는 프로필: {name}")
    shutil.copytree(FIXTURES / name, repo)
    harness("init", str(repo), "--project-name", "rehearsal", "--platform", "github", "--tracker", "github",
            "--integration-branch", "main")
    for area in scenario["areas"]:
        var_args = [arg for key, value in area["vars"].items() for arg in ("--var", f"{key}={value}")]
        harness("init", str(repo), "--area", area["dir"], "--profile", area.get("profile", name), *var_args)
    snippets = []
    for area, kind, item, var_items in scenario["scaffold"]:
        var_args = [arg for value in var_items for arg in ("--var", value)]
        output = harness("scaffold", area, kind, item, "--target", str(repo), *var_args)
        if SNIPPET_HEADER in output:
            snippets.append((area, kind, snippet_of(output)))
    if scenario["paste"]:
        PASTERS[scenario["paste"]](repo, snippets)
    return scenario


def area_verify(repo: Path, scenario: dict) -> list[str]:
    """init이 harness.json에 굳힌 영역 검증 명령(영역 순서대로). stop-verify가 실행하는 바로 그 명령이다."""
    config = json.loads((repo / "harness.json").read_text(encoding="utf-8"))
    dirs = [area["dir"] for area in scenario["areas"]]
    commands = []
    for area in config.get("areas", []):
        if area["dir"] in dirs:
            commands.extend(area["verify"])
    if not commands:
        raise RehearsalError("harness.json에 영역 검증 명령이 없다")
    return commands


def ensure_wrapper(build_root: Path) -> None:
    """PATH의 고정 버전 Gradle로 빈 빌드에서 wrapper를 만들어 빌드 루트에 복사한다."""
    if (build_root / "gradlew").is_file():
        return
    gradle = shutil.which("gradle")
    if gradle is None:
        raise RehearsalError(f"gradle 이 PATH에 없다(CI는 setup-gradle로 {GRADLE_VERSION}을 둔다)")
    empty = Path(tempfile.mkdtemp(prefix="harness-wrapper-"))
    try:
        (empty / "settings.gradle").write_text("", encoding="utf-8")
        result = subprocess.run([gradle, "--no-daemon", "-q", "wrapper", "--gradle-version", GRADLE_VERSION,
                                 "--distribution-type", "bin", "--gradle-distribution-sha256-sum", GRADLE_DISTRIBUTION_SHA256],
                                cwd=empty, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", env=child_env())
        if result.returncode != 0:
            raise RehearsalError(f"gradle wrapper 실패: {(result.stdout + result.stderr).strip()[:500]}")
        for rel in ("gradlew", "gradlew.bat", "gradle/wrapper/gradle-wrapper.jar",
                    "gradle/wrapper/gradle-wrapper.properties"):
            (build_root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(empty / rel, build_root / rel)
        (build_root / "gradlew").chmod(0o755)
    finally:
        remove_tree(empty)


def run_steps(repo: Path, commands: list[str], label: str) -> tuple[int, str]:
    """명령을 차례로 실행하고 첫 실패에서 멈춘다(stop-verify처럼 하나라도 실패하면 실패)."""
    print(f"::group::{label}", flush=True)
    code, outputs = 0, []
    try:
        for cmd in commands:
            code, output = shell(cmd, repo)
            outputs.append(output)
            if code != 0:
                break
    finally:
        print("::endgroup::", flush=True)
    return code, "".join(outputs)


def judge_negative(negative: dict, code: int, output: str) -> list[str]:
    problems = []
    if code == 0:
        problems.append("검증 명령이 통과했다(실패해야 한다)")
    for needle in negative["expect"]:
        if needle not in output:
            problems.append(f"출력에 '{needle}'이 없다")
    return problems


def report(name: str, step: str, problems: list[str]) -> bool:
    status = "통과" if not problems else "실패: " + "; ".join(problems)
    print(f"rehearsal {name} {step}: {status}", flush=True)
    return not problems


def drift_diff(repo: Path, before: dict[str, str], check_output: str) -> str:
    """`harness check`가 불일치로 보고한 파일마다 init 직후 내용과의 차이. 형식 도구가 무엇을 바꿨는지 로그에 남긴다."""
    lines = []
    for line in check_output.splitlines():
        if not line.startswith("불일치:"):
            continue
        rel = line.split(":", 1)[1].strip()
        path = repo / rel
        after = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        lines.extend(difflib.unified_diff(before.get(rel, "").splitlines(), after.splitlines(),
                                          f"{rel} (init 직후)", f"{rel} (현재)", lineterm=""))
    return "\n".join(lines)


def snapshot(repo: Path) -> dict[str, str]:
    """init·scaffold 직후의 텍스트 파일(의존성 설치 전이라 작다)."""
    files = {}
    for path in repo.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            try:
                files[path.relative_to(repo).as_posix()] = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
    return files


def rehearse(name: str, keep: bool = False) -> int:
    work = Path(tempfile.mkdtemp(prefix=f"harness-profile-{name}-"))
    repo = work / "consumer"
    failed = []
    try:
        scenario = prepare(name, repo)
        before = snapshot(repo)
        for rel in scenario["gradle_roots"]:
            ensure_wrapper(repo / rel)
        verify = area_verify(repo, scenario)
        code, _ = run_steps(repo, scenario["setup"] + scenario["format"], "준비·형식 맞춤")
        if code != 0:
            raise RehearsalError("준비 또는 형식 맞춤 명령이 실패했다(위 로그)")
        code, _ = run_steps(repo, verify, "영역 검증 명령")
        problems = [] if code == 0 else [f"영역 검증 명령 종료 코드 {code}"]
        if not problems:
            check = subprocess.run([sys.executable, str(HARNESS), "check", str(repo)], capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", env=child_env())
            if check.returncode != 0:
                problems.append(f"harness check 드리프트: {(check.stdout + check.stderr).strip()[:500]}")
                print("::group::드리프트 diff")
                print(drift_diff(repo, before, check.stdout + check.stderr))
                print("::endgroup::")
        if not report(name, "scaffold-verify", problems):
            failed.append("scaffold-verify")
        else:  # 양성이 통과해야 음성의 실패가 규칙 때문이라고 읽을 수 있다
            for negative in scenario["negatives"]:
                for rel, content in negative["files"].items():
                    write(repo, rel, content)
                code, output = run_steps(repo, scenario["format"] + verify, f"음성 {negative['name']}")
                if not report(name, negative["name"], judge_negative(negative, code, output)):
                    failed.append(negative["name"])
                for rel in negative["files"]:
                    (repo / rel).unlink()
    finally:
        if keep:
            print(f"작업 디렉터리를 남겼다: {repo}")
        else:
            remove_tree(work)
    if failed:
        print(f"::error::프로필 리허설 {name} 실패: {', '.join(failed)}")
        return 1
    print(f"프로필 리허설 {name}: 양성 1개, 음성 {len(scenario['negatives'])}개 시나리오 통과")
    return 0


def main(argv: list[str]) -> int:
    args = argv[1:]
    keep = "--keep" in args
    names = [arg for arg in args if arg != "--keep"]
    if len(names) != 1 or names[0] not in scenarios():
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # Windows 콘솔에서도 빌드 출력을 그대로 흘린다
    try:
        return rehearse(names[0], keep)
    except RehearsalError as exc:
        print(f"::error::프로필 리허설 준비 실패: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
