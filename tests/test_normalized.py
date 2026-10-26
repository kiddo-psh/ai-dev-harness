"""#140 공통 텔레메트리 v2: 두 도구의 원천 읽기·정규화·outbox 전송과 Codex Stop·SessionEnd hook."""

import contextlib
import datetime as dt
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_codex_sessions import SECRET, rollout, ts  # noqa: E402
from test_sessions import SessionRecordCase, collect, harness, run_cli  # noqa: E402
from test_summary import init_target  # noqa: E402
from test_telemetry import Collector  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / "core" / "observability" / "grafana" / "dashboards" / "harness-agentops-normalized.json"
telemetry = harness.load_telemetry()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


normalized = load("normalized_under_test", ROOT / "core" / "metrics" / "normalized.py")
sys.path.insert(0, str(ROOT / "core" / "hooks"))  # codex-hook.py가 harness_common을 같은 디렉터리에서 읽는다
codex_hook = load("codex_hook_under_test", ROOT / "core" / "hooks" / "codex-hook.py")
NO_LOCK = types.SimpleNamespace(_file_lock=lambda _path: contextlib.nullcontext())


def attrs(log):
    return {item["key"]: int(item["value"]["intValue"]) if "intValue" in item["value"]
            else next(iter(item["value"].values())) for item in log["attributes"]}


class NormalizedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        prices = dict(zip(collect.USAGE_FIELDS, [2, 10, 3, 4, 0.2]))
        self.pricing = {"currency": "USD", "as_of": "test-v1", "models": {"same": prices, "gpt-6-sol": dict(prices)}}

    def message(self, key, inp, out, model="same", stamp=None):
        return {"type": "assistant", "sessionId": "session", "cwd": str(self.repo), "gitBranch": "main",
                "timestamp": stamp or ts(5), "uuid": f"uuid-{key}",
                "message": {"id": key, "model": model, "content": [SECRET],
                            "usage": {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": 400}}}

    def claude(self, rows=None, child=False):
        path = self.root / "claude" / "projects" / "repo" / "session.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = rows or [self.message("a", 600, 50), self.message("a", 600, 60), self.message("b", 100, 5)]
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        if child:
            sub = path.with_suffix("") / "subagents" / "child.jsonl"
            sub.parent.mkdir(parents=True)
            sub.write_text(json.dumps(self.message("c", 10, 1)) + "\n", encoding="utf-8")
        return path

    def raw(self, **changes):
        record = normalized.unit("codex", "s", "request", ts(1), "same", {field: 10 for field in collect.USAGE_FIELDS},
                                 "main")
        record.update(changes)
        return record

    def send(self, records, fail=False, from_start=False, **kwargs):
        logs, headers, messages = [], [], []

        def deliver(url, sent_headers, body):
            if fail:
                raise OSError("secret must not appear")
            headers.append(sent_headers)
            for resource in body["resourceLogs"]:
                for scope in resource["scopeLogs"]:
                    logs.extend(scope["logRecords"])
            return 0, ""

        options = {"endpoint": "http://127.0.0.1:4318", "env": {}, **kwargs}
        with mock.patch.object(telemetry, "send", side_effect=deliver):
            code = normalized.send_records(telemetry, NO_LOCK, collect, "repo", self.root / "state.json", self.pricing,
                                           "test", records, 0, from_start=from_start, out=messages.append, **options)
        return code, logs, messages, headers

    def test_same_usage_and_cost_for_both_tools(self):
        self.claude([self.message("a", 600, 50, model="gpt-6-sol")])
        rollout(self.root / "codex", "session", self.repo, turns=1)
        claude, claude_errors = normalized.claude_units(self.root / "claude", [str(self.repo)], collect,
                                                        harness.hooks_common)
        codex, codex_errors = normalized.codex_units(self.root / "codex", [str(self.repo)], {}, collect)
        codex = [item for item in codex if item["kind"] == "usage"]
        self.assertEqual((claude_errors, codex_errors), (0, 0))
        self.assertEqual(claude[0]["counts"], codex[0]["counts"])
        for raw in (claude[0], codex[0]):
            record = normalized.materialize(raw, None, self.pricing, collect)
            record["id"] = "id"
            log = normalized.log_record(record, telemetry, collect, 123)
            self.assertAlmostEqual(attrs(log)["harness.cost_estimate"], 0.00178)
            self.assertNotIn(SECRET, json.dumps(log))

    def test_streaming_model_change_and_children_are_separate(self):
        self.claude(child=True)
        units, errors = normalized.claude_units(self.root / "claude", [str(self.repo)], collect, harness.hooks_common)
        self.assertEqual((errors, len(units)), (0, 3))
        self.assertEqual(sum(item["counts"]["output"] for item in units), 66)  # 스트리밍 a는 최댓값 60 한 번
        self.assertEqual(len([item for item in units if item["parent"]]), 1)
        other = normalized.claude_units(self.root / "claude", [str(self.root / "other")], collect, harness.hooks_common)
        self.assertEqual(other[0], [])
        self.claude([self.message("a", 10, 1), self.message("b", 20, 2, model="missing")])
        units, _ = normalized.claude_units(self.root / "claude", [str(self.repo)], collect, harness.hooks_common)
        self.assertEqual({item["model"] for item in units}, {"same", "missing"})

    def test_pricing_is_frozen_and_unknown_price_is_not_zero(self):
        first = normalized.materialize(self.raw(), None, self.pricing, collect)
        changed = {**self.pricing, "models": {"same": {field: 100 for field in collect.USAGE_FIELDS}}}
        later = normalized.materialize(self.raw(counts={field: 20 for field in collect.USAGE_FIELDS}), first, changed,
                                       collect)
        self.assertEqual((first["prices"], first["price_id"]), (later["prices"], later["price_id"]))
        missing = normalized.materialize(self.raw(model="missing"), None, self.pricing, collect)
        missing["id"] = "u"
        data = attrs(normalized.log_record(missing, telemetry, collect, 123))
        self.assertEqual(data["harness.cost_status"], "unpriced")
        self.assertNotIn("harness.cost_estimate", data)
        self.assertEqual(data["harness.unpriced_tokens"], 50)
        smaller = normalized.materialize(self.raw(counts={field: 1 for field in collect.USAGE_FIELDS}), first, changed,
                                         collect)
        self.assertEqual(smaller["counts"], first["counts"])  # 토큰은 역방향 갱신으로 줄지 않는다

    def test_explicit_zero_price_is_priced(self):
        self.pricing["models"]["same"] = {field: 0 for field in collect.USAGE_FIELDS}
        record = normalized.materialize(self.raw(), None, self.pricing, collect)
        record["id"] = "zero"
        data = attrs(normalized.log_record(record, telemetry, collect, 1))
        self.assertEqual((data["harness.cost_status"], data["harness.cost_estimate"]), ("priced", 0))

    def test_event_time_and_observation_time_are_distinct_across_midnight(self):
        stamp = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).replace(hour=14, minute=59, second=59,
                                                                                   microsecond=0)
        record = normalized.materialize(self.raw(ts=stamp.isoformat()), None, self.pricing, collect)
        record["id"] = "u"
        now = int((stamp + dt.timedelta(minutes=5)).timestamp() * 1e9)
        log = normalized.log_record(record, telemetry, collect, now)
        self.assertEqual(int(log["timeUnixNano"]), now)
        self.assertEqual(attrs(log)["harness.event_unix"], int(stamp.timestamp()))
        self.assertEqual(attrs(log)["harness.day"], (stamp + dt.timedelta(hours=9)).strftime("%Y-%m-%d"))

    def test_kst_boundary_keeps_first_branch(self):
        monday = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).replace(hour=15, minute=0, second=0,
                                                                                   microsecond=0)
        first = normalized.materialize(self.raw(ts=monday.isoformat(), branch="before"), None, self.pricing, collect)
        first["id"] = "boundary"
        later = normalized.materialize(self.raw(ts=(monday + dt.timedelta(hours=1)).isoformat(), branch="after"),
                                       first, self.pricing, collect)
        later["id"] = "boundary"
        data = attrs(normalized.log_record(later, telemetry, collect,
                                           int(dt.datetime.now(dt.timezone.utc).timestamp() * 1e9)))
        self.assertEqual(data["harness.branch"], "before")
        self.assertEqual(data["harness.day"], (monday + dt.timedelta(hours=9)).strftime("%Y-%m-%d"))

    def test_replay_usage_to_stop_and_restart_do_not_duplicate(self):
        record = self.raw()
        code, first, _, _ = self.send([record])
        self.assertEqual(code, 0)
        usage = [log for log in first if attrs(log)["harness.kind"] == "usage"]
        self.assertEqual(len(usage), 1)
        code, second, _, _ = self.send([record])
        self.assertEqual(code, 0)
        self.assertFalse([log for log in second if attrs(log)["harness.kind"] == "usage"])
        _, replay, _, _ = self.send([record], from_start=True)
        replay = [log for log in replay if attrs(log)["harness.kind"] == "usage"]
        self.assertEqual(attrs(usage[0])["harness.record_id"], attrs(replay[0])["harness.record_id"])
        completion = self.raw(kind="completion", key="complete", counts={}, verify="unsupported")
        _, logs, _, _ = self.send([record, completion])
        self.assertEqual([attrs(log)["harness.kind"] for log in logs], ["completion", "exporter"])
        _, logs, _, _ = self.send([record, completion])
        self.assertEqual([attrs(log)["harness.kind"] for log in logs], ["exporter"])

    def test_failed_delivery_keeps_outbox_and_price_on_restart_without_source(self):
        code, _, messages, _ = self.send([self.raw()], fail=True)
        self.assertEqual(code, 1)
        self.assertNotIn("secret", " ".join(messages))
        state = json.loads((self.root / "state.json").read_text(encoding="utf-8"))
        self.assertFalse(next(iter(state["records"].values()))["sent"])
        self.pricing["models"]["same"] = {field: 999 for field in collect.USAGE_FIELDS}
        code, logs, _, _ = self.send([])
        self.assertEqual(code, 0)
        usage = next(log for log in logs if attrs(log)["harness.kind"] == "usage")
        self.assertLess(attrs(usage)["harness.cost_estimate"], 0.001)  # 처음 고정한 단가
        health = attrs(logs[-1])
        self.assertEqual((health["harness.previous_failures"], health["harness.agent_state"]), (1, "unknown"))
        self.assertNotIn("harness.interval_seconds", health)  # 주기 전송(watch)은 두지 않는다

    def test_partial_rejection_retries_same_records(self):
        messages = []
        with mock.patch.object(telemetry, "send", return_value=(1, "never print response detail")):
            code = normalized.send_records(telemetry, NO_LOCK, collect, "repo", self.root / "state.json",
                                           self.pricing, "test", [self.raw()], 0, endpoint="http://127.0.0.1:4318",
                                           env={}, out=messages.append)
        self.assertEqual(code, 1)
        state = json.loads((self.root / "state.json").read_text(encoding="utf-8"))
        self.assertFalse(next(iter(state["records"].values()))["sent"])
        self.assertNotIn("response detail", " ".join(messages))

    def test_configured_endpoint_and_credentials_like_v1(self):
        """0.4.0(#145)과 같은 순서: 변수가 없으면 harness.json telemetry.endpoint와 사용자 자격 파일 헤더."""
        bases = []

        def credentials(base):
            bases.append(base)
            return {"Authorization": "Bearer from-file"}

        code, logs, _, headers = self.send([self.raw()], endpoint=None, configured="https://collector.example/",
                                           credentials=credentials)
        self.assertEqual(code, 0)
        self.assertEqual(bases, ["https://collector.example"])
        self.assertEqual(headers[0], {"Authorization": "Bearer from-file"})
        code, _, _, headers = self.send([self.raw(key="other")], endpoint=None, configured="https://collector.example",
                                        env={"OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Bearer%20env"},
                                        credentials=credentials)
        self.assertEqual((code, headers[0]), (0, {"Authorization": "Bearer env"}))
        code, _, messages, _ = self.send([self.raw()], endpoint=None)
        self.assertEqual(code, 2)
        self.assertIn("엔드포인트가 없다", messages[0])

    def test_legacy_reset_and_first_baseline_are_explicit(self):
        path = self.root / "codex" / "sessions" / "rollout-legacy.jsonl"
        path.parent.mkdir(parents=True)
        rows = [{"type": "session_meta", "payload": {"id": "old", "cwd": str(self.repo)}}]
        for amount in (100, 200, 30):
            rows.append({"timestamp": ts(5), "type": "event_msg", "payload": {
                "type": "token_count", "info": {"total_token_usage": {"input_tokens": amount, "output_tokens": 0}}}})
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        units, errors = normalized.codex_units(self.root / "codex", [str(self.repo)], {}, collect)
        self.assertEqual(errors, 0)
        self.assertEqual([item["counts"]["input"] for item in units], [100, 100, 30])
        self.assertEqual([item["attribution"] for item in units], ["legacy-first", "legacy-delta", "legacy-reset"])

    def test_partial_child_file_preserves_parent_usage(self):
        main = self.claude([self.message("parent", 600, 50)])
        child = main.with_suffix("") / "subagents" / "child.jsonl"
        child.parent.mkdir(parents=True)
        child.write_text("{}\n", encoding="utf-8")
        original = normalized.lines

        def source(path, *args, **kwargs):
            if path == child:
                raise OSError("do not output path or content")
            return original(path, *args, **kwargs)

        with mock.patch.object(normalized, "lines", side_effect=source):
            units, errors = normalized.claude_units(self.root / "claude", [str(self.repo)], collect,
                                                    harness.hooks_common)
        self.assertEqual((errors, len(units), units[0]["counts"]["input"]), (1, 1, 600))

    def test_dashboard_common_population_and_no_native_double_count(self):
        def walk(panels):
            for panel in panels:
                yield panel
                yield from walk(panel.get("panels", []))

        for panel in walk(json.loads(DASHBOARD.read_text(encoding="utf-8"))["panels"]):
            for target in panel.get("targets", []):
                expr = target["expr"]
                self.assertIn('harness_schema_version="2"', expr)
                self.assertNotIn("claude_code_cost_usage", expr)
                for var in ("member", "repo", "tool", "model"):
                    self.assertIn("${" + var + ":doublequote}", expr)
                self.assertIn("harness_event_unix >= ${__from:date:seconds}", expr)
                self.assertIn("harness_record_id", expr)
                self.assertIn("[7d]) by (", expr)  # unwrap 단계에서 불필요한 메타데이터 차원을 없앤다

    def test_people_table_splits_tokens_by_tool(self):
        """#156: 사람별 사용 내역에 도구별 토큰 열을 둔다. 관측 토큰과 같은 식에 도구 조건만 더한다."""
        panels = {panel["id"]: panel for panel in json.loads(DASHBOARD.read_text(encoding="utf-8"))["panels"]}
        targets = {target["refId"]: target["expr"] for target in panels[14]["targets"]}
        anchor = "harness_event_unix <= ${__to:date:seconds}"
        for ref, tool in (("E", "codex"), ("F", "claude-code")):
            self.assertEqual(targets[ref], targets["A"].replace(anchor, f'{anchor} | harness_tool="{tool}"', 1))
        organize = next(t for t in panels[14]["transformations"] if t["id"] == "organize")["options"]
        self.assertEqual((organize["renameByName"]["Value #E"], organize["renameByName"]["Value #F"]),
                         ("Codex 토큰", "Claude Code 토큰"))
        for pid in (1, 3):
            self.assertTrue(panels[pid]["description"])


class PushIntegrationTest(SessionRecordCase):
    """`telemetry push` 한 번이 v1에 이어 v2를 보낸다. 같은 PC·저장소의 Codex 세션만 읽는다."""

    def test_push_sends_v2_after_v1_without_duplicates(self):
        code, _, err = init_target(self.project, "github")
        self.assertEqual(code, 0, err)
        self.init_git()
        self.assertEqual(self.start().returncode, 0)
        rollout(Path(os.environ["CODEX_HOME"]), "c1", self.project)  # 2턴: 사용량 2, 완료 응답 2
        rollout(Path(os.environ["CODEX_HOME"]), "elsewhere", self.tmp / "other")
        collector = Collector()
        self.addCleanup(collector.close)
        code, out, err = run_cli(["telemetry", "push", str(self.project), "--endpoint", collector.url])
        self.assertEqual(code, 0, out + err)
        kinds = sorted(attrs(log)["harness.kind"] for log in collector.v2_records())
        self.assertEqual(kinds, ["completion", "completion", "exporter", "usage", "usage"])
        usage = [attrs(log) for log in collector.v2_records() if attrs(log)["harness.kind"] == "usage"]
        self.assertEqual({item["harness.session"] for item in usage}, {"c1"})
        self.assertEqual({item["harness.tool"] for item in usage}, {"codex"})
        self.assertNotIn(SECRET, json.dumps(collector.bodies))
        code, out, err = run_cli(["telemetry", "push", str(self.project), "--endpoint", collector.url])
        self.assertEqual(code, 0, out + err)
        self.assertEqual(sorted(attrs(log)["harness.kind"] for log in collector.v2_records()),
                         ["completion", "completion", "exporter", "exporter", "usage", "usage"])


class CodexHookTest(SessionRecordCase):
    """Codex Stop은 THROTTLE_SEC마다 한 번, SessionEnd는 항상 push를 띄운다."""

    def setUp(self):
        super().setUp()
        self.init_git()
        self.spawned = []
        patcher = mock.patch.object(codex_hook.common, "spawn_telemetry_push",
                                    side_effect=lambda project: self.spawned.append(project) or True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_stop_is_throttled_and_session_end_always_spawns(self):
        sub = self.project / "docs"
        sub.mkdir(exist_ok=True)
        payload = {"cwd": str(sub), "session_id": "s", "last_assistant_message": SECRET}
        self.assertTrue(codex_hook.run("stop", payload, now=1000))
        self.assertFalse(codex_hook.run("stop", payload, now=1000 + codex_hook.THROTTLE_SEC - 1))
        self.assertTrue(codex_hook.run("session-end", payload, now=1000 + codex_hook.THROTTLE_SEC - 1))
        self.assertTrue(codex_hook.run("stop", payload, now=1000 + 2 * codex_hook.THROTTLE_SEC))
        self.assertEqual(len(self.spawned), 3)
        self.assertEqual({path.resolve() for path in self.spawned}, {self.project.resolve()})  # 하위 디렉터리에서도 루트

    def test_unspawned_push_does_not_start_throttle(self):
        codex_hook.common.spawn_telemetry_push.side_effect = lambda project: False  # 설정 없는 PC
        self.assertFalse(codex_hook.run("stop", {"cwd": str(self.project)}, now=1000))
        codex_hook.common.spawn_telemetry_push.side_effect = lambda project: self.spawned.append(project) or True
        self.assertTrue(codex_hook.run("stop", {"cwd": str(self.project)}, now=1001))

    def test_outside_git_and_bad_input_stay_silent(self):
        outside = self.tmp / "plain"
        outside.mkdir()
        with mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(self.tmp)}):
            self.assertFalse(codex_hook.run("stop", {"cwd": str(outside)}))
        for stdin, argv in (("not json", ["stop"]), ("{}", ["unknown"]), ("{}", [])):
            with self.subTest(stdin=stdin, argv=argv), \
                    mock.patch("sys.stdin", io.TextIOWrapper(io.BytesIO(stdin.encode()))), \
                    mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
                    mock.patch("sys.stderr", new_callable=io.StringIO) as err:
                self.assertEqual(codex_hook.main(argv), 0)
                self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))


if __name__ == "__main__":
    unittest.main()
