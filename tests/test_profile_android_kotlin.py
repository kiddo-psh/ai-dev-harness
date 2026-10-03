"""android-kotlin 프로필(M3-4a): 실제 profiles/android-kotlin을 임시 대상 저장소에 적용한다(#51 T1~T7).

생성된 Kotlin·Konsist 코드의 컴파일·실행은 여기서 하지 않는다(로컬 JDK·SDK 없음). 실제 빌드는 리허설(M3-5)이 맡는다.
"""

import ast
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
SPEC = importlib.util.spec_from_file_location("harness_android_profile", ROOT / "bin" / "harness.py")
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)

PROFILE = "android-kotlin"
RULES = ("no-global-scope", "viewmodel-no-android-context", "screen-no-viewmodel-param", "wear-not-depend-on-app")
APP = "android/app"
WEAR = "android/wear"
APP_ARCH = f"{APP}/src/test/java/com/acme/fit/architecture"
WEAR_ARCH = f"{WEAR}/src/test/java/com/acme/fit/wear/architecture"
FIXED = "HarnessFixedRulesTest.kt"
LAYERS = "HarnessLayerArchitectureTest.kt"
VERIFY = "android/gradlew -p android :{m}:ktlintCheck :{m}:lintDebug :{m}:testDebugUnitTest :{m}:assembleDebug"


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = harness.main(argv)
    return code, out.getvalue(), err.getvalue()


class AndroidProfileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="harness-android-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.target = self.tmp / "consumer"
        code, _out, err = run(["init", str(self.target), "--platform", "github", "--tracker", "github"])
        self.assertEqual(code, 0, err)

    # --- 도우미 -------------------------------------------------------------

    def init_area(self, area, *extra):
        code, out, err = run(["init", str(self.target), "--area", area, *extra])
        self.assertEqual(code, 0, err)
        return out

    def init_app(self):
        return self.init_area(APP, "--profile", PROFILE, "--var", "base_package=com.acme.fit")

    def init_wear(self):
        return self.init_area(WEAR, "--profile", PROFILE, "--var", "module=wear",
                              "--var", "base_package=com.acme.fit.wear")

    def scaffold(self, *argv):
        return run(["scaffold", *argv, "--target", str(self.target)])

    def config(self):
        return json.loads((self.target / "harness.json").read_text(encoding="utf-8"))

    def save_config(self, config):
        (self.target / "harness.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n",
                                                  encoding="utf-8")

    def area(self, dir_):
        return next(a for a in self.config()["areas"] if a["dir"] == dir_)

    def read(self, rel):
        return (self.target / rel).read_text(encoding="utf-8")

    def files(self):
        return sorted(p.relative_to(self.target).as_posix() for p in self.target.rglob("*") if p.is_file())

    def check(self):
        code, out, err = run(["check", str(self.target)])
        return code, out + err

    # --- T1 ---------------------------------------------------------------

    def test_profile_loads(self):
        profile, base = harness.load_profile(PROFILE)
        self.assertEqual(base, ROOT / "profiles" / PROFILE)
        self.assertEqual(set(profile["scaffold"]), {"screen", "wear-screen"})
        self.assertEqual(tuple(profile["conventions"]["rules"]), RULES)
        self.assertEqual({entry["kind"] for entry in profile["conventions"]["files"]}, {"fixed", "configured"})
        self.assertEqual(profile["vars"]["module"]["default"], "app")
        self.assertNotIn("default", profile["vars"]["base_package"])  # 필수 변수

    # --- T2 ---------------------------------------------------------------

    def test_init_phone_and_wear_areas(self):
        out = self.init_app()
        self.assertIn("com.lemonappdev:konsist", out)
        self.assertIn("dependencyLocking", out)
        out = self.init_wear()
        self.assertIn("android/gradlew -p android :wear:dependencies --write-locks", out)
        for dir_, module, arch in ((APP, "app", APP_ARCH), (WEAR, "wear", WEAR_ARCH)):
            with self.subTest(area=dir_):
                area = self.area(dir_)
                self.assertEqual(area["verify"], [VERIFY.format(m=module)])
                strict = area["trigger_paths"]["strict"]
                for pattern in ("**/build.gradle.kts", "**/AndroidManifest.xml", "**/proguard-rules.pro",
                                "*.jks", "*.keystore", "gradle.lockfile"):
                    self.assertIn(pattern, strict)
                self.assertIn("/src/test/", area["test_paths"])
                self.assertEqual(len(area["triggers"]), 6)  # 프로필 5개 + 프로필 설정 변경 트리거
                self.assertEqual(area["triggers"][-1], harness.PROFILE_TRIGGER)
                self.assertEqual(area["layers"], {"ui": ["..ui.."], "domain": ["..domain.."], "data": ["..data.."]})
                self.assertEqual(area["allow"], {"ui": ["domain", "data"], "domain": [], "data": ["domain"]})
                self.assertEqual(area["disabled_rules"], {})
                self.assertEqual(area["vars"]["module"], module)
                self.assertEqual(area["vars"]["app_module"], "app")
                generated = [f for f in self.files() if f.startswith(f"{dir_}/") and f.endswith(".kt")]
                self.assertEqual(generated, [f"{arch}/{FIXED}", f"{arch}/{LAYERS}"])
                for rel in generated:
                    text = self.read(rel)
                    self.assertNotIn("{{", text)
                    self.assertNotIn("}}", text)
                    self.assertIn(f'.scopeFromProduction("{module}")' if rel.endswith(LAYERS)
                                  else f'private val module = "{module}"', text)
                self.assertIn(VERIFY.format(m=module), self.read(f"{dir_}/AGENTS.md"))
        self.assertIn("\npackage com.acme.fit.wear.architecture\n", self.read(f"{WEAR_ARCH}/{FIXED}"))
        self.assertIn('val appModule = "app"', self.read(f"{WEAR_ARCH}/{FIXED}"))
        self.assertEqual(self.check()[0], 0)

    # --- T3 ---------------------------------------------------------------

    def test_scaffold_screen(self):
        self.init_app()
        before = self.files()
        code, out, err = self.scaffold(APP, "screen", "WorkoutSummary")
        self.assertEqual(code, 0, err)
        src = f"{APP}/src/main/java/com/acme/fit/ui/workoutsummary"
        test = f"{APP}/src/test/java/com/acme/fit/ui/workoutsummary"
        expected = [f"{src}/WorkoutSummaryScreen.kt", f"{src}/WorkoutSummaryRoute.kt",
                    f"{src}/WorkoutSummaryViewModel.kt", f"{src}/WorkoutSummaryUiState.kt",
                    f"{test}/WorkoutSummaryViewModelTest.kt"]
        self.assertEqual(sorted(set(self.files()) - set(before)), sorted(expected))
        for rel in expected:
            text = self.read(rel)
            self.assertTrue(text.startswith("package com.acme.fit.ui.workoutsummary\n"), rel)
            self.assertNotIn("{{", text)

        screen = self.read(f"{src}/WorkoutSummaryScreen.kt")
        signature = re.search(r"fun WorkoutSummaryScreen\((.*?)\n\)", screen, re.S)
        self.assertIsNotNone(signature)
        self.assertIn("uiState: WorkoutSummaryUiState", signature.group(1))
        self.assertNotIn("ViewModel", signature.group(1))
        self.assertIn("@Preview", screen)

        route = self.read(f"{src}/WorkoutSummaryRoute.kt")
        self.assertIn("collectAsStateWithLifecycle()", route)
        self.assertIn("viewModel { WorkoutSummaryViewModel() }", route)

        view_model = self.read(f"{src}/WorkoutSummaryViewModel.kt")
        self.assertIn("val uiState: StateFlow<WorkoutSummaryUiState>", view_model)
        self.assertIn("class WorkoutSummaryViewModel : ViewModel()", view_model)  # DI 없는 생성자 주입(A-4)
        for forbidden in ("android.content.Context", "android.app.Activity", "android.view.View", "GlobalScope",
                          "javax.inject", "dagger", "koin"):
            self.assertNotIn(forbidden, view_model)

        self.assertIn("data class WorkoutSummaryUiState(", self.read(f"{src}/WorkoutSummaryUiState.kt"))
        test_text = self.read(f"{test}/WorkoutSummaryViewModelTest.kt")
        for word in ("runTest {", "StandardTestDispatcher()", "Dispatchers.setMain(dispatcher)", "Dispatchers.resetMain()"):
            self.assertIn(word, test_text)

        self.assertIn('composable(route = "workout-summary") {\n    WorkoutSummaryRoute()\n}', out)
        self.assertIn("import com.acme.fit.ui.workoutsummary.WorkoutSummaryRoute", out)
        self.assertEqual(self.check()[0], 0)  # 생성물은 check 대상이 아니다

    # --- T4 ---------------------------------------------------------------

    def test_scaffold_wear_screen(self):
        self.init_app()
        self.init_wear()
        before = self.files()
        code, out, err = self.scaffold(WEAR, "wear-screen", "HeartRate")
        self.assertEqual(code, 0, err)
        src = f"{WEAR}/src/main/java/com/acme/fit/wear/ui/heartrate"
        test = f"{WEAR}/src/test/java/com/acme/fit/wear/ui/heartrate"
        expected = [f"{src}/HeartRateScreen.kt", f"{src}/HeartRateRoute.kt", f"{src}/HeartRateViewModel.kt",
                    f"{src}/HeartRateUiState.kt", f"{test}/HeartRateViewModelTest.kt"]
        self.assertEqual(sorted(set(self.files()) - set(before)), sorted(expected))
        screen = self.read(f"{src}/HeartRateScreen.kt")
        for word in ("import androidx.wear.compose.foundation.lazy.ScalingLazyColumn",
                     "import androidx.wear.compose.material3.AppScaffold",
                     "import androidx.wear.compose.material3.ScreenScaffold",
                     "ScreenScaffold(scrollState = listState", "ScalingLazyColumn(", "AppScaffold {", "@Preview"):
            self.assertIn(word, screen)
        self.assertNotIn("androidx.compose.material3", screen)  # 폰 Material 3가 아니라 Wear Material 3
        signature = re.search(r"fun HeartRateScreen\((.*?)\n\)", screen, re.S)
        self.assertNotIn("ViewModel", signature.group(1))
        self.assertIn("class HeartRateViewModel : ViewModel()", self.read(f"{src}/HeartRateViewModel.kt"))
        self.assertIn("runTest {", self.read(f"{test}/HeartRateViewModelTest.kt"))
        self.assertIn("SwipeDismissableNavHost", out)
        self.assertIn("AppScaffold", out)
        self.assertIn('composable(route = "heart-rate") {\n    HeartRateRoute()\n}', out)
        self.assertIn("import androidx.wear.compose.navigation.composable", out)
        # 워치 스캐폴드는 폰 모듈 영역에 파일을 만들지 않는다
        self.assertFalse(any(f.startswith(f"{APP}/src/main/") for f in self.files()))

    # --- T5 ---------------------------------------------------------------

    def test_disable_each_fixed_rule(self):
        self.init_app()
        rel = f"{APP_ARCH}/{FIXED}"
        full = self.read(rel)
        for rule in RULES:
            self.assertIn(f"// harness:rule {rule}\n", full)
        markers = {
            "no-global-scope": "fun noGlobalScope()",
            "viewmodel-no-android-context": "fun viewModelDoesNotReferenceAndroidUi()",
            "screen-no-viewmodel-param": "fun screenDoesNotTakeViewModel()",
            "wear-not-depend-on-app": "fun moduleDoesNotDependOnAppModule()",
        }
        for rule in RULES:
            with self.subTest(rule=rule):
                config = self.config()
                next(a for a in config["areas"] if a["dir"] == APP)["disabled_rules"] = {rule: "테스트에서 끈다"}
                self.save_config(config)
                self.init_area(APP, "--force")
                text = self.read(rel)
                self.assertNotIn(f"harness:rule {rule}", text)
                self.assertNotIn(markers[rule], text)
                for other in RULES:
                    if other != rule:
                        self.assertIn(f"// harness:rule {other}\n", text)
                        self.assertIn(markers[other], text)
                self.assertIn("fun moduleHasProductionSources()", text)  # 항상 남는 범위 확인
                self.assertNotIn("\n\n\n", text)  # 블록이 빠져도 빈 줄이 겹치지 않는다(ktlint)
                self.assertTrue(text.endswith("\n}\n"))
                self.assertEqual(self.check()[0], 0)
        config = self.config()
        next(a for a in config["areas"] if a["dir"] == APP)["disabled_rules"] = {rule: "전부 끈다" for rule in RULES}
        self.save_config(config)
        self.init_area(APP, "--force")
        text = self.read(rel)
        self.assertNotIn("harness:", text)
        self.assertNotIn("\n\n\n", text)
        self.assertIn("fun moduleHasProductionSources()", text)
        # 리뷰 F1: 전부 끄면 쓰지 않는 import가 남는다. check 관리 파일이라 ktlint 검사를 파일에서 꺼 둬야 한다
        code = "\n".join(line for line in text.splitlines()
                         if not line.startswith(("import ", "//", "@file:")))
        unused = [line for line in text.splitlines() if line.startswith("import ")
                  and line.rsplit(".", 1)[-1] not in code]
        self.assertEqual(unused, ["import com.lemonappdev.konsist.api.verify.assertFalse"])
        self.assertIn('@file:Suppress("ktlint:standard:no-unused-imports")', text)

    # --- T6 ---------------------------------------------------------------

    def test_layer_config_renders_konsist(self):
        self.init_app()
        rel = f"{APP_ARCH}/{LAYERS}"
        self.assertIn("\n".join([
            "            .assertArchitecture {",
            '                val ui = Layer("ui", "..ui..")',
            '                val domain = Layer("domain", "..domain..")',
            '                val data = Layer("data", "..data..")',
            "",
            "                ui.dependsOn(domain, data)",
            "                domain.dependsOnNothing()",
            "                data.dependsOn(domain)",
            "            }",
        ]), self.read(rel))
        self.assertIn("import com.lemonappdev.konsist.api.architecture.KoArchitectureCreator.assertArchitecture",
                      self.read(rel))
        # allow 변경은 다시 생성하기 전까지 check 불일치다
        config = self.config()
        area = next(a for a in config["areas"] if a["dir"] == APP)
        area["allow"]["ui"] = ["domain"]
        area["layers"]["presentation"] = ["..presentation.."]
        area["allow"]["presentation"] = ["ui"]
        self.save_config(config)
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn(f"불일치: {rel}", out)
        self.init_area(APP, "--force")
        self.assertEqual(self.check()[0], 0)
        text = self.read(rel)
        self.assertIn("                ui.dependsOn(domain)\n", text)
        self.assertIn('                val presentation = Layer("presentation", "..presentation..")\n', text)
        self.assertIn("                presentation.dependsOn(ui)\n", text)
        self.assertNotIn("dependsOn(domain, data)", text)

    # --- T7 ---------------------------------------------------------------

    def test_verify_runs_gradle_root_wrapper_from_repo_root(self):
        """PR #54 Codex P1·결정표 Q2 (a): 영역 검증 명령은 저장소 루트에서 실행되므로 Gradle 빌드 루트의 wrapper를 부른다."""
        self.init_area(APP, "--profile", PROFILE, "--var", "base_package=com.acme.fit", "--var", "gradle_root=mobile")
        self.assertEqual(self.config()["areas"][0]["verify"], [VERIFY.format(m="app").replace("android", "mobile")])
        for root in (".", "apps/android"):
            with self.subTest(root=root):
                # 재실행은 이전 verify를 유지하므로(엔진 규칙) 영역 항목을 지우고 다시 만든다
                config = self.config()
                config["areas"] = []
                self.save_config(config)
                self.init_area(APP, "--force", "--profile", PROFILE, "--var", "base_package=com.acme.fit",
                               "--var", f"gradle_root={root}")
                self.assertTrue(self.config()["areas"][0]["verify"][0].startswith(f"{root}/gradlew -p {root} :app:"))
        for bad in ("..", "../android", "/abs", "a/../b", "a\\b"):
            with self.subTest(bad=bad):
                code, _out, _err = run(["init", str(self.target), "--area", APP, "--force", "--var", f"gradle_root={bad}"])
                self.assertEqual(code, 2)

    def test_global_scope_ignores_comments_and_strings(self):
        """PR #54 Codex: 주석·KDoc·문자열의 GlobalScope 언급은 위반이 아니고 실제 사용만 잡는다."""
        self.init_app()
        text = self.read(f"{APP_ARCH}/{FIXED}")
        literals = re.findall(r'val (commentsAndStrings|globalScope) = Regex\(("(?:\\.|[^"\\])*")\)', text)
        patterns = {name: ast.literal_eval(literal) for name, literal in literals}  # Kotlin 문자열 이스케이프는 Python과 같다
        self.assertEqual(set(patterns), {"commentsAndStrings", "globalScope"})

        def violates(source):
            return re.search(patterns["globalScope"], re.sub(patterns["commentsAndStrings"], "", source)) is not None

        self.assertTrue(violates("fun f() {\n    GlobalScope.launch { }\n}\n"))
        self.assertTrue(violates('val s = "x" + GlobalScope.toString()\n'))
        self.assertFalse(violates("/**\n * GlobalScope 대신 viewModelScope를 쓴다\n */\nfun f() = Unit\n"))
        self.assertFalse(violates("// GlobalScope 금지\nfun f() = Unit\n"))
        self.assertFalse(violates('val message = "GlobalScope는 쓰지 않는다"\n'))
        self.assertFalse(violates('val message = "escaped \\" GlobalScope"\n'))

    def test_templates_follow_ktlint_basics(self):
        self.init_app()
        self.init_wear()
        for argv in ((APP, "screen", "WorkoutSummary"), (WEAR, "wear-screen", "HeartRate")):
            code, _out, err = self.scaffold(*argv)
            self.assertEqual(code, 0, err)
        rendered = [f for f in self.files() if f.endswith(".kt")]
        self.assertEqual(len(rendered), 14)  # 컨벤션 2개 × 2영역 + 스캐폴드 5개 × 2
        for rel in rendered:
            with self.subTest(file=rel):
                text = self.read(rel)
                self.assertNotIn("\t", text)
                self.assertNotIn("\r", text)
                self.assertTrue(text.endswith("\n") and not text.endswith("\n\n"), "파일 끝 줄바꿈 하나")
                self.assertNotIn("\n\n\n", text)
                self.assertIsNone(re.search(r"^import .*\*$", text, re.M), "와일드카드 import")
                imports = re.findall(r"^import (\S+)$", text, re.M)
                self.assertEqual(imports, sorted(imports), "import 사전순")
                self.assertEqual(len(imports), len(set(imports)))
                for number, line in enumerate(text.split("\n"), 1):
                    self.assertEqual(line, line.rstrip(), f"{number}행 끝 공백")
                    self.assertLessEqual(len(line), 140, f"{number}행 길이")
                    stripped = line.lstrip(" ")
                    if stripped.startswith("*"):  # KDoc 본문은 " * " 정렬이라 한 칸 더 들어간다
                        continue
                    self.assertEqual((len(line) - len(stripped)) % 4, 0, f"{number}행 들여쓰기: {line!r}")


if __name__ == "__main__":
    unittest.main()
