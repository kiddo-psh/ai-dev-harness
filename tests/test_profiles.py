"""프로필 엔진(M3-1): profile.json 검증, init --profile, 컨벤션 파일, scaffold. 픽스처 프로필 `demo`를 쓴다."""

import importlib.util
import io
import json
import re
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("harness_profiles", ROOT / "bin" / "harness.py")
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)

FIXTURE = ROOT / "tests" / "fixtures" / "profile-engine"


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = harness.main(argv)
    return code, out.getvalue(), err.getvalue()


class ProfileTestBase(unittest.TestCase):
    """픽스처 프로필을 임시 profiles 디렉터리로 복사해 쓴다(테스트가 프로필을 고쳐도 원본은 그대로)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="harness-profile-"))
        self.profiles = self.tmp / "profiles"
        shutil.copytree(FIXTURE, self.profiles)
        patcher = patch.object(harness, "PROFILES_DIR", self.profiles)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.target = self.tmp / "consumer"
        code, _out, err = run(["init", str(self.target), "--platform", "github", "--tracker", "github"])
        self.assertEqual(code, 0, err)

    def profile_json(self):
        return json.loads((self.profiles / "demo" / "profile.json").read_text(encoding="utf-8"))

    def write_profile(self, data):
        (self.profiles / "demo" / "profile.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def init_area(self, *extra):
        return run(["init", str(self.target), "--area", "backend", *extra])

    def init_demo(self, *extra):
        code, out, err = self.init_area("--profile", "demo", "--var", "base_package=com.acme.app", *extra)
        self.assertEqual(code, 0, err)
        return out

    def config(self):
        return json.loads((self.target / "harness.json").read_text(encoding="utf-8"))

    def save_config(self, config):
        (self.target / "harness.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n",
                                                  encoding="utf-8")

    def area(self):
        return next(a for a in self.config()["areas"] if a["dir"] == "backend")

    def read(self, rel):
        return (self.target / rel).read_text(encoding="utf-8")

    def files(self):
        return sorted(p.relative_to(self.target).as_posix() for p in self.target.rglob("*") if p.is_file())


class ProfileSchemaTest(ProfileTestBase):
    def test_fixture_profile_loads(self):
        profile, base = harness.load_profile("demo")
        self.assertEqual(base, self.profiles / "demo")
        self.assertEqual(list(profile["vars"]), ["base_package", "module", "error_package", "src_root"])
        self.assertEqual(set(profile["conventions"]["rules"]), {"no-field-injection", "tx-in-service"})

    def test_invalid_profiles_rejected(self):
        def mutate(change):
            data = self.profile_json()
            change(data)
            return data

        cases = {
            "unknown key": mutate(lambda d: d.update(typo=1)),
            "name mismatch": mutate(lambda d: d.update(name="other")),
            "no description": mutate(lambda d: d.pop("description")),
            "bad trigger_paths": mutate(lambda d: d.update(trigger_paths={"blocker": []})),
            "allow unknown layer": mutate(lambda d: d["allow"].update(service=["nowhere"])),
            "allow key not layer": mutate(lambda d: d["allow"].update(nowhere=[])),
            "escaping scaffold src": mutate(lambda d: d["scaffold"]["domain"]["files"][0].update(src="../x")),
            "missing scaffold src": mutate(lambda d: d["scaffold"]["domain"]["files"][0].update(src="Nope.txt")),
            "escaping dest": mutate(lambda d: d["scaffold"]["domain"]["files"][0].update(dest="../{{name}}.txt")),
            "unknown dest placeholder": mutate(lambda d: d["scaffold"]["domain"]["files"][0].update(dest="{{nope}}")),
            "unknown convention kind": mutate(lambda d: d["conventions"]["files"][0].update(kind="other")),
            "reserved var name": mutate(lambda d: d["vars"].update(base_path={"description": "x"})),
            "var without description": mutate(lambda d: d["vars"].update(extra={})),
            "bad var pattern": mutate(lambda d: d["vars"]["module"].update(pattern="(")),
            "kind var shadows profile var": mutate(
                lambda d: d["scaffold"]["screen"]["vars"].update(module={"description": "x"})),
            "unknown verify placeholder": mutate(lambda d: d.update(verify=["{{nope}}"])),
            "format unknown placeholder": mutate(lambda d: d["conventions"]["formats"]["layer_defs"].update(
                layer="{{nope}}")),
            "format without layer": mutate(lambda d: d["conventions"]["formats"]["layer_defs"].pop("layer")),
            "rule without block": mutate(lambda d: d["conventions"]["rules"].update({"never-used": "x"})),
        }
        for label, data in cases.items():
            with self.subTest(label):
                self.write_profile(data)
                with self.assertRaises(harness.HarnessError):
                    harness.load_profile("demo")
        for bad in ("Demo", "../demo", "", "missing"):
            with self.subTest(name=bad), self.assertRaises(harness.HarnessError):
                harness.load_profile(bad)


class InitProfileTest(ProfileTestBase):
    def test_init_area_with_profile(self):
        out = self.init_demo()
        area = self.area()
        self.assertEqual(area["profile"], "demo")
        self.assertEqual(area["vars"], {"base_package": "com.acme.app", "module": "app",
                                        "error_package": "com.acme.app.global.error", "src_root": "src"})
        self.assertEqual(area["verify"], ["build app", "test com.acme.app"])
        self.assertEqual(area["triggers"], ["데모 트리거", harness.PROFILE_TRIGGER])
        self.assertEqual(area["review_focus"], ["데모 관점"])
        self.assertEqual(area["trigger_paths"], {"strict": ["/build.conf"], "standard": ["/shared/"]})
        self.assertEqual(area["test_paths"], ["/test/"])
        self.assertEqual(list(area["layers"]), ["controller", "service", "repository"])
        self.assertEqual(area["allow"], {"controller": ["service"], "service": ["repository"]})
        self.assertEqual(area["disabled_rules"], {})
        self.assertIn("backend/AGENTS.md", self.files())
        self.assertIn("backend/test/com/acme/app/architecture/FixedRules.txt", self.files())
        self.assertIn("backend/test/com/acme/app/architecture/LayerRules.txt", self.files())
        self.assertIn("안내: 모듈 app 의 빌드 파일에 데모 의존성을 추가한다", out)
        self.assertIn("build app", self.read("backend/AGENTS.md"))
        self.assertIn(harness.PROFILE_TRIGGER, self.read("backend/AGENTS.md"))
        code, out, _err = run(["check", str(self.target)])
        self.assertEqual(code, 0, out)

    def test_var_validation(self):
        cases = [
            ("missing required", ["--profile", "demo"]),
            ("pattern mismatch", ["--profile", "demo", "--var", "base_package=Com.Acme"]),
            ("undeclared var", ["--profile", "demo", "--var", "base_package=a.b", "--var", "nope=1"]),
            ("malformed var", ["--profile", "demo", "--var", "base_package"]),
            ("duplicate var", ["--profile", "demo", "--var", "base_package=a", "--var", "base_package=b"]),
            ("placeholder in value", ["--profile", "demo", "--var", "base_package=a", "--var", "src_root={{x}}"]),
            ("missing profile", ["--profile", "nope", "--var", "base_package=a"]),
            ("var without profile", ["--verify-cmd", "t", "--var", "base_package=a"]),
        ]
        before = self.files()
        for label, extra in cases:
            with self.subTest(label):
                code, _out, err = self.init_area(*extra)
                self.assertEqual(code, 2)
                self.assertTrue(err.startswith("오류:"), err)
                self.assertEqual(self.files(), before)
        for flag in (["--profile", "demo"], ["--var", "a=b"]):
            with self.subTest(root_flag=flag):
                code, _out, _err = run(["init", str(self.tmp / "other"), *flag])
                self.assertEqual(code, 2)

    def test_explicit_args_override_profile(self):
        self.init_demo("--verify-cmd", "make check", "--trigger", "내 트리거", "--review-focus", "내 관점",
                       "--var", "module=core")
        area = self.area()
        self.assertEqual(area["verify"], ["make check"])
        self.assertEqual(area["triggers"], ["내 트리거", harness.PROFILE_TRIGGER])
        self.assertEqual(area["review_focus"], ["내 관점"])
        self.assertEqual(area["vars"]["module"], "core")

    def test_rerun_keeps_profile_and_vars(self):
        self.init_demo("--var", "module=core")
        config = self.config()
        config["areas"][0]["layers"]["dto"] = ["..dto.."]
        config["areas"][0]["triggers"].append("추가 트리거")
        self.save_config(config)
        code, _out, err = self.init_area("--force")
        self.assertEqual(code, 0, err)
        area = self.area()
        self.assertEqual(area["profile"], "demo")
        self.assertEqual(area["vars"]["module"], "core")
        self.assertIn("dto", area["layers"])
        self.assertEqual(area["triggers"].count(harness.PROFILE_TRIGGER), 1)
        # 이미 있는 파일은 --force 없이 덮어쓰지 않는다
        code, _out, err = self.init_area()
        self.assertEqual(code, 2)
        self.assertIn("--force", err)
        # 다른 프로필로 바꾸기는 거부한다
        shutil.copytree(self.profiles / "demo", self.profiles / "demo-two")
        data = json.loads((self.profiles / "demo-two" / "profile.json").read_text(encoding="utf-8"))
        data["name"] = "demo-two"
        (self.profiles / "demo-two" / "profile.json").write_text(json.dumps(data), encoding="utf-8")
        code, _out, err = self.init_area("--force", "--profile", "demo-two")
        self.assertEqual(code, 2)
        self.assertIn("demo", err)
        self.assertEqual(self.area()["profile"], "demo")

    def test_plain_area_unchanged(self):
        """프로필 없는 영역은 예전과 같다: --verify-cmd 필수, 프로필 키 없음."""
        code, _out, err = self.init_area()
        self.assertEqual(code, 2)
        self.assertIn("--verify-cmd", err)
        code, _out, err = self.init_area("--verify-cmd", "make test")
        self.assertEqual(code, 0, err)
        self.assertFalse(set(self.area()) & harness.AREA_PROFILE_KEYS)


class ConventionTest(ProfileTestBase):
    LAYERS = "backend/test/com/acme/app/architecture/LayerRules.txt"
    FIXED = "backend/test/com/acme/app/architecture/FixedRules.txt"

    def check(self):
        code, out, err = run(["check", str(self.target)])
        return code, out + err

    def test_check_detects_drift_and_layer_change(self):
        self.init_demo()
        self.assertEqual(self.check()[0], 0)
        path = self.target / self.FIXED
        original = path.read_text(encoding="utf-8")
        path.write_text(original + "손 수정\n", encoding="utf-8")
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn(f"불일치: {self.FIXED}", out)
        path.write_text(original, encoding="utf-8")
        config = self.config()
        config["areas"][0]["allow"]["repository"] = ["service"]
        self.save_config(config)
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn(f"불일치: {self.LAYERS}", out)
        code, _out, err = self.init_area("--force")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.check()[0], 0)
        self.assertIn("repository -> <service>", self.read(self.LAYERS))

    def test_layer_formats_render(self):
        self.init_demo()
        self.assertEqual(self.read(self.LAYERS), "\n".join([
            "package com.acme.app",
            "layer(controller) = ['..controller..']\n"
            "layer(service) = ['..service..']\n"
            "layer(repository) = ['..repository..' | '..repo..']",
            "controller -> <service>; service -> <repository>; repository -> (none)",
            'json {"controller": ["..controller.."], "service": ["..service.."], '
            '"repository": ["..repository..", "..repo.."]} '
            '{"controller": ["service"], "service": ["repository"]}',
            "",
        ]))

    def test_fixed_file_does_not_get_layer_values(self):
        data = self.profile_json()
        data["conventions"]["files"][0]["kind"] = "fixed"
        (self.profiles / "demo" / "conventions" / "FixedRules.txt").write_text(
            "{{layer_rules}}\n// harness:rule no-field-injection\n// harness:end\n"
            "// harness:rule tx-in-service\n// harness:end\n", encoding="utf-8")
        self.write_profile(data)
        code, _out, err = self.init_area("--profile", "demo", "--var", "base_package=a")
        self.assertEqual(code, 2)
        self.assertIn("layer_rules", err)

    def test_disabled_rule_removes_block(self):
        self.init_demo()
        config = self.config()
        config["areas"][0]["disabled_rules"] = {"tx-in-service": "레거시 모듈이 controller에서 트랜잭션을 연다(#12)"}
        self.save_config(config)
        code, _out, err = self.init_area("--force")
        self.assertEqual(code, 0, err)
        text = self.read(self.FIXED)
        self.assertNotIn("tx-in-service", text)
        self.assertIn("// harness:rule no-field-injection\nrule no-field-injection\n// harness:end\n// 끝", text)
        for bad in ({"tx-in-service": " "}, {"no-such-rule": "이유"}):
            with self.subTest(disabled=bad):
                config["areas"][0]["disabled_rules"] = bad
                self.save_config(config)
                code, _out, err = self.init_area("--force")
                self.assertEqual(code, 2)

    def test_rule_marker_errors(self):
        rules = {"a": "규칙 a"}
        bad = {
            "unclosed": "// harness:rule a\nx\n",
            "nested": "// harness:rule a\n// harness:rule a\n// harness:end\n",
            "orphan end": "x\n// harness:end\n",
            "undeclared": "// harness:rule b\n// harness:end\n",
        }
        for label, text in bad.items():
            with self.subTest(label), self.assertRaises(harness.HarnessError):
                harness.apply_rule_blocks(text, rules, {}, "t")
        text = "a\n// harness:rule a\nb\n// harness:end\nc"
        self.assertEqual(harness.apply_rule_blocks(text, rules, {}, "t"), (text, {"a"}))
        self.assertEqual(harness.apply_rule_blocks(text, rules, {"a": "이유"}, "t")[0], "a\nc")

    def test_area_profile_keys_validated(self):
        base = {"project_name": "demo", "platform": "github", "tracker": "github",
                "default_branch": "main", "integration_branch": "main"}
        area = {"dir": "backend", "verify": ["t"]}
        bad = [
            {**area, "vars": {"a": "b"}},
            {**area, "profile": "Bad Name"},
            {**area, "profile": "demo", "vars": {"a": 1}},
            {**area, "profile": "demo", "layers": {"a": []}},
            {**area, "profile": "demo", "layers": {"a": ["x"]}, "allow": {"a": ["b"]}},
            {**area, "profile": "demo", "disabled_rules": ["a"]},
            {**area, "profile": "demo", "disabled_rules": {"a": ""}},
        ]
        for item in bad:
            with self.subTest(area=item), self.assertRaises(harness.HarnessError):
                harness.validate_config({**base, "areas": [item]}, "test")
        harness.validate_config({**base, "areas": [{**area, "profile": "demo", "layers": {"a": ["x"]},
                                                    "allow": {"a": []}, "disabled_rules": {"r": "이유"}}]}, "test")


class ScaffoldTest(ProfileTestBase):
    CONTROLLER = "backend/src/com/acme/app/domain/moviereview/MovieReviewController.txt"
    SERVICE = "backend/src/com/acme/app/domain/moviereview/MovieReviewService.txt"

    def setUp(self):
        super().setUp()
        self.init_demo()

    def scaffold(self, *argv):
        return run(["scaffold", *argv, "--target", str(self.target)])

    def test_scaffold_creates_files_and_prints_snippet(self):
        before = self.files()
        code, out, err = self.scaffold("backend", "domain", "MovieReview")
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(set(self.files()) - set(before)), sorted([self.CONTROLLER, self.SERVICE]))
        controller = self.read(self.CONTROLLER)
        self.assertEqual(controller, "package com.acme.app.domain.moviereview.controller;\n"
                                     "class MovieReviewController { /* movieReview movie-review movie_review "
                                     "MovieReview */ }\n// 오류: com.acme.app.global.error\n")
        for rel in (self.CONTROLLER, self.SERVICE):
            self.assertNotIn("{{", self.read(rel))
        self.assertIn('route("/movie-review", MovieReviewController)', out)
        # 생성물은 팀 소유라 check 대상이 아니다
        self.assertEqual(run(["check", str(self.target)])[0], 0)

    def test_existing_file_aborts_without_writing(self):
        (self.target / self.SERVICE).parent.mkdir(parents=True)
        (self.target / self.SERVICE).write_text("팀 코드\n", encoding="utf-8")
        code, _out, err = self.scaffold("backend", "domain", "MovieReview")
        self.assertEqual(code, 2)
        self.assertIn(self.SERVICE, err)
        self.assertFalse((self.target / self.CONTROLLER).exists())
        self.assertEqual(self.read(self.SERVICE), "팀 코드\n")

    def test_project_template_override(self):
        override = self.target / ".harness" / "templates" / "demo" / "domain"
        override.mkdir(parents=True)
        (override / "Service.txt").write_text("// 프로젝트 템플릿 {{name_snake}}\n", encoding="utf-8")
        (override / "snippet.txt").write_text("프로젝트 조각 {{name_camel}}\n", encoding="utf-8")
        code, out, err = self.scaffold("backend", "domain", "MovieReview")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read(self.SERVICE), "// 프로젝트 템플릿 movie_review\n")
        self.assertIn("class MovieReviewController", self.read(self.CONTROLLER))
        self.assertIn("프로젝트 조각 movieReview", out)

    def test_errors(self):
        config = self.config()
        config["areas"].append({"dir": "plain", "verify": ["t"]})
        self.save_config(config)
        data = self.profile_json()
        data["scaffold"]["domain"]["vars"] = {"sub": {"description": "하위 경로", "default": "x"}}
        data["scaffold"]["domain"]["files"][0]["dest"] = "{{sub}}/{{name}}.txt"
        self.write_profile(data)
        before = self.files()
        cases = [
            ("unknown area", ["frontend", "domain", "Movie"]),
            ("area without profile", ["plain", "domain", "Movie"]),
            ("unknown kind", ["backend", "widget", "Movie"]),
            ("bad name", ["backend", "domain", "9Movie"]),
            ("bad name chars", ["backend", "domain", "Movie/../x"]),
            ("escaping dest", ["backend", "domain", "Movie", "--var", "sub=.."]),
            ("undeclared var", ["backend", "domain", "Movie", "--var", "nope=1"]),
        ]
        for label, argv in cases:
            with self.subTest(label):
                code, _out, err = self.scaffold(*argv)
                self.assertEqual(code, 2, err)
                self.assertEqual(self.files(), before)

    def test_name_variants(self):
        expected = {
            "MovieReview": ("MovieReview", "movieReview", "movie-review", "movie_review", "moviereview"),
            "movie-review": ("MovieReview", "movieReview", "movie-review", "movie_review", "moviereview"),
            "APIKey": ("APIKey", "apiKey", "api-key", "api_key", "apikey"),
            "user_profile": ("UserProfile", "userProfile", "user-profile", "user_profile", "userprofile"),
            "Movie": ("Movie", "movie", "movie", "movie", "movie"),
        }
        for name, values in expected.items():
            with self.subTest(name=name):
                variants = harness.name_variants(name)
                self.assertEqual(variants["name"], name)
                self.assertEqual(tuple(variants[k] for k in harness.NAME_VARIANTS[1:]), values)

    def test_optional_empty_var_collapses_path(self):
        code, _out, err = self.scaffold("backend", "screen", "Home")
        self.assertEqual(code, 0, err)
        self.assertTrue((self.target / "backend/src/pages/HomePage/index.txt").is_file())
        code, _out, err = self.scaffold("backend", "screen", "Home", "--var", "area=auth")
        self.assertEqual(code, 0, err)
        self.assertTrue((self.target / "backend/src/pages/auth/HomePage/index.txt").is_file())
        code, _out, _err = self.scaffold("backend", "screen", "Other", "--var", "area=Bad")
        self.assertEqual(code, 2)


class StackNeutralTest(unittest.TestCase):
    """P-9: core·CLI는 프로필(스택) 이름을 모른다."""

    WORDS = ("spring", "react", "android")

    def test_core_has_no_profile_names(self):
        names = {p.name for p in (ROOT / "profiles").iterdir() if (p / "profile.json").is_file()}
        pattern = re.compile("|".join(re.escape(w) for w in sorted(names | set(self.WORDS))), re.IGNORECASE)
        hits = []
        for base in (ROOT / "bin", ROOT / "core"):
            for path in base.rglob("*"):
                if not path.is_file() or "__pycache__" in path.parts:
                    continue
                for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if pattern.search(line):
                        hits.append(f"{path.relative_to(ROOT).as_posix()}:{number}: {line.strip()}")
        self.assertEqual(hits, [])


class DocsTest(unittest.TestCase):
    def read(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_roadmap_and_install_updated(self):
        roadmap = self.read("docs/roadmap.md")
        m3 = roadmap[roadmap.index("### M3."):roadmap.index("### M4.")]
        self.assertIn("5~7주차", m3)
        self.assertIn("세 프로필", m3)
        self.assertIn("profile.json", m3)
        self.assertIn("android-kotlin", m3)
        self.assertIn("- [x] M3-1", m3)
        for rel in ("docs/roadmap.md", "profiles/README.md", "docs/install.md"):
            with self.subTest(rel=rel):
                self.assertNotIn("verify.json", self.read(rel))
        adr = self.read("docs/adr/0004-core-profile-split.md")
        self.assertIn("profile.json", adr[adr.index("## 결과"):])
        install = self.read("docs/install.md")
        contract = install[install.index("## 13."):]
        for word in ("scaffold", "--profile", "--var", ".harness/templates/", "disabled_rules", "layers", "allow"):
            with self.subTest(word=word):
                self.assertIn(word, contract)
        readme = self.read("profiles/README.md")
        for word in ("profile.json", "harness:rule", "formats", ".harness/templates/"):
            with self.subTest(word=word):
                self.assertIn(word, readme)


if __name__ == "__main__":
    unittest.main()
