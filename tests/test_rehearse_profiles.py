"""프로필 리허설 스크립트(.github/scripts/rehearse_profiles.py, M3-5) 테스트(plans/56.md T4).

Gradle·npm 빌드는 CI `profiles` job이 맡는다(결정 H-4). 여기서는 시나리오 표, fixture 모양, 외부 도구 없이 도는
준비 단계(fixture 복사 → init → scaffold → 조각 붙이기)와 렌더된 영역 검증 명령, workflow job 정의를 본다.
"""

import importlib.util
import io
import json
import re
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / ".github" / "scripts" / "rehearse_profiles.py"
FIXTURES = ROOT / "tests" / "fixtures" / "profiles"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rp = load("rehearse_profiles", SCRIPT)
harness = load("harness_rehearse_profiles", ROOT / "bin" / "harness.py")

# 영역 검증 명령은 저장소 루트에서 실행된다(stop-verify, 결정 Q2 답 (a)). 프로필이 렌더한 명령의 기대 모양
ROOT_COMMANDS = {
    "spring-java": [r"cd backend && \./gradlew build"],
    "react-ts": [rf"npm --prefix frontend run {script}" for script in ("lint", "format:check", "test:run", "build")],
    "android-kotlin": [rf"android/gradlew -p android :{module}:ktlintCheck :{module}:lintDebug "
                       rf":{module}:testDebugUnitTest :{module}:assembleDebug" for module in ("app", "wear")],
}


def job_lines(body, name):
    """ci.yml에서 job 하나의 본문 줄(주석·빈 줄·줄 끝 주석 제외)."""
    block = re.search(rf"^  {re.escape(name)}:\n((?:(?:    .*)?\n)+)", body, re.M).group(1)
    return [line.split("  #")[0].rstrip() for line in block.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


class ScenarioTableTest(unittest.TestCase):
    def test_every_profile_has_scenario_and_fixture(self):
        profiles = {path.parent.name for path in (ROOT / "profiles").glob("*/profile.json")}
        table = rp.scenarios()
        self.assertEqual(set(table), profiles)
        self.assertEqual({path.name for path in FIXTURES.iterdir() if path.is_dir()}, profiles)
        for name, scenario in table.items():
            with self.subTest(name):
                profile = json.loads((ROOT / "profiles" / name / "profile.json").read_text(encoding="utf-8"))
                self.assertTrue(scenario["scaffold"])
                for area, kind, _item, _vars in scenario["scaffold"]:
                    self.assertIn(kind, profile["scaffold"])
                    self.assertIn(area, [a["dir"] for a in scenario["areas"]])
                self.assertTrue(scenario["negatives"])  # 음성 시나리오가 없으면 규칙이 꺼져도 모른다(H-3)
                for negative in scenario["negatives"]:
                    self.assertTrue(negative["files"] and negative["expect"], negative["name"])
                    for rel in negative["files"]:
                        self.assertFalse((FIXTURES / name / rel).exists(), rel)  # 음성 파일은 실행 중에만 만든다
                for rel in scenario["gradle_roots"]:
                    self.assertTrue(any((FIXTURES / name / rel / f).is_file()
                                        for f in ("settings.gradle", "settings.gradle.kts")), rel)

    def test_negative_scenarios_cover_decided_rules(self):
        """H-3·A-12: controller→repository, mocks import, alt 없는 img, ViewModel Context, contentDescription."""
        names = {n["name"] for scenario in rp.scenarios().values() for n in scenario["negatives"]}
        self.assertEqual(names, {"controller-calls-repository", "page-imports-mocks", "img-without-alt",
                                 "viewmodel-holds-context", "image-without-content-description"})

    def test_judge_negative_needs_failure_and_reason(self):
        negative = {"name": "x", "files": {}, "expect": ["[no-mocks-import]"]}
        self.assertEqual(rp.judge_negative(negative, 1, "error [no-mocks-import] ..."), [])
        self.assertTrue(rp.judge_negative(negative, 0, "[no-mocks-import]"))  # 통과하면 실패
        self.assertTrue(rp.judge_negative(negative, 1, "npm error ENOENT"))  # 도구 오류는 기대한 실패가 아니다


class FixtureTest(unittest.TestCase):
    def test_no_gradle_wrapper_committed(self):
        """H-2: wrapper jar를 넣지 않고 CI의 고정 버전 Gradle로 만든다."""
        for path in FIXTURES.rglob("*"):
            self.assertNotIn(path.name, ("gradlew", "gradlew.bat", "gradle-wrapper.jar", "gradle-wrapper.properties"),
                             path)

    def test_versions_are_pinned(self):
        """H-5: 동적 버전(+, latest, ^, ~)을 쓰지 않는다. npm은 lock 파일과 함께 둔다."""
        frontend = FIXTURES / "react-ts" / "frontend"
        package = json.loads((frontend / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((frontend / "package-lock.json").read_text(encoding="utf-8"))
        for section in ("dependencies", "devDependencies"):
            for name, version in package[section].items():
                self.assertRegex(version, r"^\d+\.\d+\.\d+$", name)
                self.assertEqual(lock["packages"][f"node_modules/{name}"]["version"], version, name)
        self.assertEqual(lock["packages"][""]["devDependencies"], package["devDependencies"])
        gradle_files = [*FIXTURES.rglob("*.gradle"), *FIXTURES.rglob("*.gradle.kts"), *FIXTURES.rglob("*.toml")]
        self.assertTrue(gradle_files)
        for path in gradle_files:
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"""version\s*=?\s*['"][^'"]*(\+|latest)""", path)
            self.assertNotRegex(text, r"""['"][\w.-]+:[\w.-]+:[^'"]*\+['"]""", path)

    def test_gradle_version_matches_ci(self):
        body = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(f'gradle-version: "{rp.GRADLE_VERSION}"', body)


class PrepareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="harness-rehearse-profiles-"))
        self.addCleanup(rp.remove_tree, self.tmp)

    def prepare(self, name):
        repo = self.tmp / name
        rp.prepare(name, repo)
        return repo

    def assert_no_placeholders(self, repo):
        for path in repo.rglob("*"):
            if path.is_file() and path.suffix in (".java", ".kt", ".ts", ".tsx", ".js", ".json", ".md"):
                self.assertNotIn("{{", path.read_text(encoding="utf-8"), path)

    def assert_check_clean(self, repo):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = harness.main(["check", str(repo)])
        self.assertEqual(code, 0, out.getvalue() + err.getvalue())

    def test_spring_java(self):
        repo = self.prepare("spring-java")
        base = repo / "backend/src/main/java/com/example/rehearsal"
        for rel in ("domain/moviereview/controller/MovieReviewController.java",
                    "domain/moviereview/repository/MovieReviewRepository.java"):
            self.assertTrue((base / rel).is_file(), rel)
        tests = repo / "backend/src/test/java/com/example/rehearsal"
        for rel in ("architecture/FixedRulesArchitectureTest.java", "architecture/LayerRulesArchitectureTest.java",
                    "domain/moviereview/controller/MovieReviewControllerTest.java"):
            self.assertTrue((tests / rel).is_file(), rel)
        self.assert_no_placeholders(repo)
        self.assert_check_clean(repo)

    def test_react_ts_pastes_routes(self):
        repo = self.prepare("react-ts")
        src = repo / "frontend/src"
        self.assertTrue((src / "pages/movies/MovieDetailPage/index.tsx").is_file())
        self.assertTrue((src / "api/movieReview.ts").is_file())
        paths = (src / "routes/paths.ts").read_text(encoding="utf-8")
        self.assertIn("  movieDetail: '/movie-detail',\n  // rehearsal:route-pattern", paths)
        self.assertIn("  movieDetail: () => ROUTE_PATTERN.movieDetail,\n  // rehearsal:path", paths)
        router = (src / "routes/router.tsx").read_text(encoding="utf-8")
        self.assertIn("import MovieDetailPage from '../pages/movies/MovieDetailPage';\n// rehearsal:import", router)
        self.assertIn("  { path: ROUTE_PATTERN.movieDetail, element: <MovieDetailPage /> },\n  // rehearsal:route",
                      router)
        self.assertTrue((repo / "frontend/eslint.harness.js").is_file())
        self.assert_no_placeholders(repo)
        self.assert_check_clean(repo)

    def test_android_kotlin_pastes_nav_graphs(self):
        repo = self.prepare("android-kotlin")
        app = repo / "android/app/src/main/java/com/example/rehearsal"
        self.assertTrue((app / "ui/workoutsummary/WorkoutSummaryViewModel.kt").is_file())
        host = (app / "RehearsalNavHost.kt").read_text(encoding="utf-8")
        self.assertIn("import com.example.rehearsal.ui.workoutsummary.WorkoutSummaryRoute\n", host)
        self.assertEqual(host.count("import androidx.navigation.compose.composable\n"), 1)  # 있는 import는 더하지 않는다
        self.assertIn('        composable(route = "workout-summary") {\n            WorkoutSummaryRoute()\n        }\n'
                      "        // rehearsal:destinations", host)
        wear = (repo / "android/wear/src/main/java/com/example/rehearsal/wear/WearNavHost.kt").read_text("utf-8")
        self.assertIn("import com.example.rehearsal.wear.ui.heartrate.HeartRateRoute\n", wear)
        self.assertIn('            composable(route = "heart-rate") {\n                HeartRateRoute()\n', wear)
        for module, package in (("app", "com/example/rehearsal"), ("wear", "com/example/rehearsal/wear")):
            arch = repo / f"android/{module}/src/test/java/{package}/architecture"
            self.assertTrue((arch / "HarnessFixedRulesTest.kt").is_file(), module)
            # 계층 기본값(ui·domain·data)마다 생산 소스가 있어야 Konsist 계층 검사가 빈 계층으로 실패하지 않는다
            for layer in ("ui", "domain", "data"):
                self.assertTrue(any((repo / f"android/{module}/src/main/java/{package}/{layer}").rglob("*.kt")),
                                f"{module} {layer}")
        self.assert_no_placeholders(repo)
        self.assert_check_clean(repo)

    def test_verify_commands_run_from_repo_root(self):
        """Q2 답 (a): 렌더된 영역 검증 명령은 저장소 루트에서 실행할 수 있어야 한다(stop-verify와 같은 위치)."""
        for name, expected in ROOT_COMMANDS.items():
            with self.subTest(name):
                if name != "android-kotlin" and not hasattr(harness, "COMMAND_NAMES"):
                    self.skipTest("#55(프로필 verify의 area_dir) 병합 전")
                repo = self.prepare(name)
                commands = rp.area_verify(repo, rp.scenarios()[name])
                self.assertEqual(len(commands), len(expected), commands)
                for command, pattern in zip(commands, expected):
                    self.assertRegex(command, f"^{pattern}$")

    def test_paste_needs_marker(self):
        path = self.tmp / "router.tsx"
        path.write_text("export const x = 1;\n", encoding="utf-8")
        with self.assertRaises(rp.RehearsalError):
            rp.insert_at_marker(path, "rehearsal:route", ["a"])
        with self.assertRaises(rp.RehearsalError):
            rp.snippet_of("3개 파일을 생성했다")


class MainTest(unittest.TestCase):
    def test_usage(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(rp.main(["rehearse_profiles.py"]), 2)
            self.assertEqual(rp.main(["rehearse_profiles.py", "vue"]), 2)
            self.assertEqual(rp.main(["rehearse_profiles.py", "react-ts", "spring-java"]), 2)


class ProfilesJobTest(unittest.TestCase):
    def test_profiles_job(self):
        """H-1·H-5: 필수 체크가 아닌 별도 job, 읽기 권한, 자격 증명 미보존, SHA 고정 액션, 프로필마다 단계 하나."""
        lines = job_lines(WORKFLOW.read_text(encoding="utf-8"), "profiles")
        self.assertEqual(lines, [
            "    runs-on: ubuntu-latest",
            "    timeout-minutes: 45",
            "    permissions:",
            "      contents: read",
            "    steps:",
            "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
            "        with:",
            "          persist-credentials: false",
            "      - uses: actions/setup-java@de7274f081f381c8f8158605e0321c36c376e2e6",
            "        with:",
            "          distribution: temurin",
            '          java-version: "21"',
            "          cache: gradle",
            "          cache-dependency-path: |",
            "            tests/fixtures/profiles/**/*.gradle*",
            "            tests/fixtures/profiles/**/libs.versions.toml",
            "      - uses: gradle/actions/setup-gradle@0723195856401067f7a2779048b490ace7a47d7c",
            "        with:",
            f'          gradle-version: "{rp.GRADLE_VERSION}"',
            "          cache-disabled: true",
            "      - uses: actions/setup-node@820762786026740c76f36085b0efc47a31fe5020",
            "        with:",
            '          node-version: "22"',
            "          cache: npm",
            "          cache-dependency-path: tests/fixtures/profiles/react-ts/frontend/package-lock.json",
            "      - name: spring-java",
            "        run: python3 .github/scripts/rehearse_profiles.py spring-java",
            "      - name: react-ts",
            "        if: ${{ !cancelled() }}",
            "        run: python3 .github/scripts/rehearse_profiles.py react-ts",
            "      - name: android-kotlin",
            "        if: ${{ !cancelled() }}",
            "        run: python3 .github/scripts/rehearse_profiles.py android-kotlin",
        ])
        joined = "\n".join(lines)
        for needle in ("secrets.", "token", "TOKEN", "continue-on-error"):
            self.assertNotIn(needle, joined)


if __name__ == "__main__":
    unittest.main()
