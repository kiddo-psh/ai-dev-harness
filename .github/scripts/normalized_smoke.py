#!/usr/bin/env python3
"""공통 텔레메트리 v2(#140) 스모크 검사. `observability_smoke.py`에 이어 CI(또는 로컬 compose)에서만 실행한다.

시험 기록을 실제로 보내므로 운영 수집기에서 실행하지 않는다. 두 도구의 같은 사용량, 진행 중 갱신·재전송 중복 제거,
단가 미등록, 하루 늦은 전송의 사건 날짜 귀속, 필터, 600단위 묶음을 보내고 "harness 팀 사용량" 대시보드의 모든 쿼리를
Grafana로 실행한다.

    GRAFANA_ADMIN_PASSWORD=... python3 .github/scripts/normalized_smoke.py
"""

from __future__ import annotations

import contextlib
import datetime as dt
import importlib.util
import json
import sys
import tempfile
import types
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASHBOARDS = ROOT / "core" / "observability" / "grafana" / "dashboards"
MEMBER = "normalized-smoke-v2"
REPO = "normalized-fixture"
BULK_REPO = "normalized-cardinality-fixture"
KST = dt.timezone(dt.timedelta(hours=9))


def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


smoke = module("normalized_smoke_base", ROOT / ".github" / "scripts" / "observability_smoke.py")
normalized = module("normalized_smoke_source", ROOT / "core" / "metrics" / "normalized.py")
telemetry = module("normalized_smoke_telemetry", ROOT / "core" / "metrics" / "telemetry.py")
collect = module("normalized_smoke_collect", ROOT / "core" / "metrics" / "collect.py")


def provisioned(dashboard: dict) -> None:
    """CI는 디렉터리 프로비저닝으로 들어온다. 로컬 기존 Grafana면 같은 정의를 API로 넣는다."""
    try:
        existing = smoke.request(f"{smoke.GRAFANA}/api/dashboards/uid/{dashboard['uid']}", auth=True)
        if existing.get("meta", {}).get("provisioned"):
            return
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    smoke.request(f"{smoke.GRAFANA}/api/dashboards/db", {"dashboard": dashboard, "overwrite": True}, auth=True)


def main() -> int:
    dashboard = json.loads((DASHBOARDS / "harness-agentops-normalized.json").read_text(encoding="utf-8"))
    smoke.wait(lambda: smoke.request(f"{smoke.GRAFANA}/api/health").get("database") == "ok", "Grafana 기동")
    provisioned(dashboard)
    prices = dict(zip(collect.USAGE_FIELDS, [2, 10, 3, 4, 0.2]))
    pricing = {"currency": "USD", "as_of": "fixture-v1", "models": {"fixture": prices}}
    now = dt.datetime.now(dt.timezone.utc)
    stamp = (now - dt.timedelta(minutes=5)).isoformat()
    late = (now - dt.timedelta(days=1)).isoformat()
    counts = dict(zip(collect.USAGE_FIELDS, [600, 50, 0, 0, 400]))
    records = []
    for tool in ("claude-code", "codex"):
        records.append(normalized.unit(tool, f"{tool}-fixture", "request", stamp, "fixture", dict(counts), "main"))
        records.append(normalized.unit(tool, f"{tool}-fixture", "complete", stamp, "fixture", {}, "main",
                                       kind="completion", verify="pass" if tool == "claude-code" else "unsupported"))
    ones = {field: 1 for field in collect.USAGE_FIELDS}
    records.append(normalized.unit("codex", "late-fixture", "late", late, "missing", dict(ones), "main"))  # 단가 없음
    records.append(normalized.unit("codex", "late-priced-fixture", "late-priced", late, "fixture", dict(ones), "main"))
    env = {"OTEL_EXPORTER_OTLP_HEADERS": f"X-Harness-Member={MEMBER}"}
    no_lock = types.SimpleNamespace(_file_lock=lambda _path: contextlib.nullcontext())

    def push(repo: str, state: Path, items: list[dict], from_start: bool = False) -> None:
        code = normalized.send_records(telemetry, no_lock, collect, repo, state, pricing, "fixture", items, 0,
                                       endpoint=smoke.COLLECTOR, env=env, from_start=from_start)
        if code:
            sys.exit(f"{repo} 전송 실패: {code}")

    with tempfile.TemporaryDirectory() as temporary:
        state = Path(temporary) / "state.json"
        push(REPO, state, records)
        push(REPO, state, records, from_start=True)  # 재전송: 같은 ID라 중앙에서 한 번만 센다
        for record in records:  # 진행 중 usage가 갱신된 뒤 완료: 토큰은 마지막 스냅샷 한 번
            if record["kind"] == "usage" and record["key"] == "request":
                record["counts"]["output"] = 60
        push(REPO, state, records)
        bulk = [normalized.unit("codex", "bulk-fixture", str(index), stamp, "fixture", dict(ones), "main")
                for index in range(600)]
        push(BULK_REPO, Path(temporary) / "bulk.json", bulk)

    start, end = int((now - dt.timedelta(days=7)).timestamp()), int(now.timestamp())

    def query(target: dict, repo: str = REPO, tool: str = ".*", model: str = ".*", measure: str = "tokens"):
        expr = target["expr"].replace("${__from:date:seconds}", str(start)).replace("${__to:date:seconds}", str(end))
        for name, value in {"member": MEMBER, "repo": repo, "tool": tool, "model": model}.items():
            expr = expr.replace("${" + name + ":doublequote}", json.dumps(value))
        return smoke.query({**target, "expr": expr.replace("${measure:raw}", measure)})

    panels = {panel["id"]: panel for panel in smoke.dashboard_panels(dashboard["panels"])}

    def scalar(pid: int, **kwargs) -> float:
        return smoke.scalar(query(panels[pid]["targets"][0], **kwargs))

    expected_cost = (2 * (600 * 2 + 60 * 10 + 400 * 0.2) + sum(prices.values())) / 1e6
    smoke.wait(lambda: abs(scalar(1) - expected_cost) < 1e-9, "중복 제거·갱신된 비용")
    failures = []

    def check(actual, want, what: str) -> None:
        if abs(actual - want) > 1e-9:
            failures.append(f"{what}: {actual} != {want}")

    check(scalar(2), 2, "완료 응답(사용량과 따로 한 번씩)")
    check(scalar(3), 5, "단가 미등록 토큰")
    check(scalar(4), 4, "청구 단위 수")
    check(scalar(2, tool="codex"), 1, "도구 필터")
    check(scalar(4, model="missing"), 1, "모델 필터")
    check(scalar(4, repo="missing"), 0, "저장소 필터")
    check(scalar(13), 2130, "토큰 합계(미등록 포함, 재전송 제외)")
    for measure, want in (("tokens", 2130), ("cost", expected_cost)):
        check(sum(smoke.scalar(query(target, measure=measure)) for target in panels[5]["targets"]), want,
              f"사람별 {measure} 모집단")
    late_day = (now - dt.timedelta(days=1)).astimezone(KST).strftime("%Y-%m-%d")
    if not any(row["metric"].get("harness_day") == late_day for row in query(panels[6]["targets"][1])):
        failures.append("늦게 보낸 기록이 사건 날짜가 아니라 전송 날짜로 묶였다")
    diagnosis = json.loads((DASHBOARDS / "harness-agentops.json").read_text(encoding="utf-8"))
    status = next(panel for panel in smoke.dashboard_panels(diagnosis["panels"]) if panel["id"] == 110)
    check(smoke.scalar(query(status["targets"][1])), 0, "방금 보낸 전송 상태가 24시간 전송 없음으로 표시")
    smoke.wait(lambda: scalar(4, repo=BULK_REPO) == 600, "600단위 묶음")
    check(scalar(1, repo=BULK_REPO), 600 * sum(prices.values()) / 1e6, "600단위 비용")
    runs = 0
    for panel in smoke.dashboard_panels(dashboard["panels"]):
        for target in panel.get("targets", []):
            try:
                query(target)
            except (urllib.error.URLError, ValueError) as exc:
                failures.append(f"{panel['title']}/{target['refId']}: {exc}")
            runs += 1
    for failure in failures:
        print(f"실패: {failure}")
    print(f"팀 사용량 대시보드 쿼리 {runs}개 실행, 실패 {len(failures)}개")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
