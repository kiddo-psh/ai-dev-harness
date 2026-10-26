#!/usr/bin/env python3
"""두 도구(Claude Code·Codex)의 사용량을 같은 계약으로 정규화해 OTLP 로그로 보낸다(#140, 공통 텔레메트리 v2).

`telemetry push`가 기존(v1) 기록을 보낸 뒤 이어서 부른다. 키트에서는 `core/metrics/normalized.py`, 대상 저장소에서는
`init`이 넣는 `.harness/metrics/normalized.py`를 읽는다. 계약과 해석은 `docs/telemetry-v2.md`를 따른다.

- 원천의 청구 단위(Claude API 메시지, Codex `token_usage_record` 한 줄)마다 토큰 스냅샷을 보낸다. 같은 단위는 도구·세션·
  종류·원천 키로 만든 `harness.record_id`가 같으므로 중앙에서 ID별 최댓값을 합산해 재전송·스트리밍 갱신을 한 번만 센다.
- LogRecord 시각은 전송 시각이고 사건 시각은 `harness.event_unix`·`harness.day`(KST)에 둔다. 늦게 보내도 Loki의 스트림
  순서 제한에 걸리지 않고 사건 기간으로 조회된다.
- 단가·차원(브랜치·모델·부모)은 단위를 처음 준비할 때 고정해 공용 git 디렉터리의 `harness/telemetry-v2.json`(outbox)에
  저장한다. 네트워크 전에 저장하고 수집기가 받은 묶음만 완료 표시한다.
- 허용한 ID·시각·토큰 필드만 읽는다. 프롬프트·응답 본문·코드·transcript 경로·인증정보는 보내지도 저장하지도 않는다.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import time
from pathlib import Path

SCHEMA = 2
STATE_FILE = "telemetry-v2.json"
RETENTION_SEC = 7 * 86400  # 운영 Loki 보관 기간. 이보다 오래된 원천 사건은 새로 보내지 않는다
KST = dt.timezone(dt.timedelta(hours=9))
UNKNOWN_BRANCH = "미지정"
# 줄 전체를 JSON으로 읽기 전에 거르는 표식. 이 밖의 줄(대화 본문 등)은 해석하지 않는다
MARKERS = ('"usage"', '"session_meta"', '"turn_context"', '"token_usage_record"', '"event_msg"', '"stop"')
SAVED = {"ts", "branch", "model", "parent", "price_id", "price_as_of", "prices", "currency", "counts", "id",
         "signature", "sent", "kind", "session", "tool"}


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
                          .encode("ascii")).hexdigest()


def lines(path: Path, probe: bool = False):
    """(줄 번호, 기록). 깨진 줄은 건너뛰고 끝나지 않은 마지막 줄은 다음 실행에서 읽는다. probe가 아니면 표식이 있는 줄만."""
    with path.open(encoding="utf-8", errors="replace") as stream:
        for number, line in enumerate(stream):
            if not line.endswith("\n"):
                continue
            if not probe and not any(marker in line for marker in MARKERS):
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                yield number, record


def unit(tool: str, session: str, key: str, stamp, model, counts: dict, branch=None, parent=None,
         kind: str = "usage", verify: str | None = None) -> dict:
    """원천 한 단위. kind는 `usage`(토큰) 또는 `completion`(완료 응답)."""
    return {"tool": tool, "session": session, "key": key, "ts": stamp, "model": model or "unknown", "counts": counts,
            "branch": branch or UNKNOWN_BRANCH, "parent": parent or "", "kind": kind, "verify": verify}


def codex_units(home: Path, roots: list[str], timelines: dict, collect) -> tuple[list[dict], int]:
    """(Codex 단위, 읽기 오류 수). 이 저장소 worktree에서 연 세션만 읽는다. `token_usage_record`가 있으면 그 줄이 청구
    단위이고, 없는 옛 형식은 `token_count` 누적값의 증가분을 단위로 삼는다(최초 기준이 없으면 legacy-first)."""
    found, errors = [], 0
    for path in sorted((home / "sessions").glob("**/rollout-*.jsonl")):
        matched = False
        try:
            records = lines(path, probe=True)
            _, first = next(records)
            meta = first.get("payload", {}) if first.get("type") == "session_meta" else {}
            root = collect.codex_root_of(meta.get("cwd"), roots)
            session = meta.get("id")
            if root is None or not isinstance(session, str):
                continue
            matched = True
            records = lines(path)
            next(records)
            parent = meta.get("parent_thread_id")
            branch = (meta.get("git") or {}).get("branch")
            model, legacy, native = "unknown", {}, False
            for number, record in records:
                body = record.get("payload")
                if not isinstance(body, dict):
                    continue
                stamp = record.get("timestamp")
                moment = collect.parse_ts(stamp)
                if moment is None:
                    continue
                current = collect.branch_at(timelines.get(root, []), moment, branch)
                if record.get("type") == "turn_context":
                    model = body.get("model") or model
                counts, attribution = None, "request"
                if record.get("type") == "token_usage_record":
                    counts = collect._codex_usage(body.get("usage"))
                    native = native or counts is not None
                elif record.get("type") == "event_msg" and body.get("type") == "token_count" and not native:
                    cumulative = collect._codex_usage((body.get("info") or {}).get("total_token_usage"))
                    if cumulative:
                        attribution = "legacy-delta" if legacy else "legacy-first"
                        if sum(cumulative.values()) < sum(legacy.values()):  # 누적 리셋은 새 구간으로 센다
                            attribution, legacy = "legacy-reset", {}
                        counts = {field: max(value - legacy.get(field, 0), 0) for field, value in cumulative.items()}
                        legacy = cumulative
                if counts is not None:
                    item = unit("codex", session, str(number), stamp, model, counts, current, parent)
                    item["attribution"] = attribution
                    found.append(item)
                if record.get("type") == "event_msg" and body.get("type") == "task_complete" and not parent:
                    # Codex 완료 응답에는 검증 결과를 잇는 계약이 없다. 성공으로 채우지 않고 unsupported로 둔다
                    found.append(unit("codex", session, f"complete:{number}", stamp, model, {}, current,
                                      kind="completion", verify="unsupported"))
        except (OSError, ValueError, TypeError, AttributeError, StopIteration):
            errors += int(matched)
    return found, errors


def claude_units(home: Path, roots: list[str], collect, common) -> tuple[list[dict], int]:
    """(Claude 단위, 읽기 오류 수). API 메시지 ID마다 스트리밍 usage의 필드별 최댓값 한 번만 세고 최초 시각을 고정한다.
    서브에이전트 transcript는 `<세션>:<파일>` 세션으로 따로 읽어 부모 누적에 다시 더하지 않는다."""
    found, errors = [], 0
    for path in sorted((home / "projects").glob("*/*.jsonl")):
        matched = False
        try:
            root, header = None, {}
            for number, header in lines(path, probe=True):
                if header.get("cwd"):
                    root = collect.codex_root_of(header["cwd"], roots)
                    break
                if number >= 100:
                    break
            if root is None:
                continue
            matched = True
            session = header.get("sessionId") or path.stem
            files = [(path, session, "")]
            files += [(child, f"{session}:{child.stem}", session)
                      for child in sorted((path.with_suffix("") / "subagents").glob("*.jsonl"))]
            for source, sid, parent in files:
                messages: dict[str, dict] = {}
                try:
                    for _number, record in lines(source):
                        if record.get("cwd") and collect.codex_root_of(record["cwd"], roots) is None:
                            continue
                        message = record.get("message")
                        if record.get("type") != "assistant" or not isinstance(message, dict) \
                                or not isinstance(message.get("usage"), dict):
                            continue
                        key, stamp = message.get("id") or record.get("uuid"), record.get("timestamp")
                        if not isinstance(key, str) or collect.parse_ts(stamp) is None:
                            continue
                        counts = common._message_usage(message["usage"])
                        previous = messages.get(key)
                        if previous:
                            counts = {field: max(value, previous["counts"].get(field, 0))
                                      for field, value in counts.items()}
                            stamp = previous["ts"]
                        messages[key] = unit("claude-code", sid, key, stamp, message.get("model"), counts,
                                             record.get("gitBranch"), parent)
                except (OSError, ValueError, TypeError, AttributeError):
                    errors += 1
                found.extend(messages.values())
        except (OSError, ValueError, TypeError, AttributeError):
            errors += int(matched)
    return found, errors


def completions(dirs: list[tuple[str, Path]], collect) -> tuple[list[dict], int]:
    """(Claude 완료 응답, 읽기 오류 수). 키트 Stop 기록(`sessions.jsonl`의 stop)이 원천이다. 서브에이전트는 세지 않는다.
    종료 검증 `none`은 not-run, `error`·누락은 unknown이다."""
    found, errors = [], 0
    for _worktree, directory in dirs:
        path = directory / "sessions.jsonl"
        if not path.exists():
            continue
        try:
            for _number, record in lines(path):
                if record.get("tool") != "claude-code" or record.get("event") != "stop" or record.get("parent"):
                    continue
                if not isinstance(record.get("session"), str) or collect.parse_ts(record.get("ts")) is None:
                    continue
                verify = record.get("verify") or "unknown"
                verify = {"none": "not-run", "error": "unknown"}.get(verify, verify)
                found.append(unit("claude-code", record["session"], f"complete:{record['ts']}", record["ts"],
                                  record.get("model"), {}, record.get("branch"), kind="completion", verify=verify))
        except (OSError, ValueError, TypeError):
            errors += 1
    return found, errors


def materialize(record: dict, old: dict | None, pricing: dict, collect) -> dict:
    """보낼 단위. 이전에 준비한 단위가 있으면 시각·차원·단가를 그대로 두고 토큰은 줄이지 않는다. 처음이면 지금 가격표의
    모델 단가를 고정한다. 단가가 없는 모델(`prices` None)과 명시적 0원 단가를 구분한다."""
    result = dict(record)
    if old:
        result.update({key: old[key] for key in
                       ("ts", "branch", "model", "parent", "price_id", "price_as_of", "prices", "currency")})
        result["counts"] = ({field: max(record["counts"].get(field, 0), old["counts"].get(field, 0))
                             for field in collect.USAGE_FIELDS} if record["kind"] == "usage" else {})
        if record["kind"] == "completion":
            result["verify"] = old.get("verify", record.get("verify"))
    else:
        prices = collect.model_prices(record["model"], pricing)
        result.update(prices=prices, currency=pricing["currency"], price_as_of=pricing.get("as_of", "unspecified"),
                      price_id=fingerprint({"as_of": pricing.get("as_of"), "currency": pricing["currency"],
                                            "prices": prices}))
    return result


def log_record(record: dict, telemetry, collect, now: int) -> dict:
    """준비한 단위 → OTLP LogRecord. now는 전송 시각(ns)."""
    moment = collect.parse_ts(record["ts"])
    fields = {"harness.schema_version": SCHEMA, "harness.kind": record["kind"],
              # Loki 스트림을 v1 세션 기록과 나눈다. 실제 세션은 harness.session
              "session.id": "v2:" + record["session"], "harness.session": record["session"],
              "harness.record_id": record["id"], "harness.tool": record["tool"], "model": record["model"],
              "harness.branch": record["branch"], "harness.parent": record["parent"],
              "harness.event_unix": int(moment.timestamp()),
              "harness.day": dt.datetime.fromtimestamp(moment.timestamp(), KST).strftime("%Y-%m-%d"),
              "harness.price_id": record["price_id"], "harness.price_as_of": record["price_as_of"],
              "harness.currency": record["currency"], "harness.agent_state": "unknown",
              "harness.delay_seconds": max(0, int(now / 1e9 - moment.timestamp())),
              "harness.attribution": record.get("attribution", "request")}
    if record["kind"] == "usage":
        fields.update({f"harness.tokens.{field}": value for field, value in record["counts"].items()})
        fields["harness.sample"] = 1
        prices = record["prices"]
        fields["harness.cost_status"] = "priced" if prices is not None else "unpriced"
        fields["harness.unpriced_tokens"] = sum(record["counts"].values()) if prices is None else 0
        if prices is not None:
            fields["harness.cost_estimate"] = round(
                sum(value * prices[field] for field, value in record["counts"].items()) / 1e6, 9)
    else:
        fields["harness.completed"] = 1
        fields["harness.verify"] = record["verify"]
    return {"timeUnixNano": str(now), "observedTimeUnixNano": str(now),
            "body": {"stringValue": f"harness.v2.{record['kind']} {record['id']}"},
            "attributes": telemetry.attributes(fields), "severityNumber": 9, "severityText": "INFO"}


def send_records(telemetry, common, collect, repo: str, state_path: Path, pricing: dict, version: str,
                 records: list[dict], errors: int, endpoint: str | None = None, env=None, dry_run: bool = False,
                 from_start: bool = False, out=print, source_status: dict | None = None,
                 configured: str | None = None, credentials=None) -> int:
    """정규화 단위를 보낸다. 주소·헤더는 v1 push와 같은 순서로 정한다(인자 → OTEL 변수 → `harness.json`
    telemetry.endpoint, 헤더 변수가 없으면 사용자 자격 파일, #145). 종료 코드: 0, 1(전송 실패·잠금·원천 읽기 오류),
    2(설정 오류)."""
    env = os.environ if env is None else env
    try:
        url = None if dry_run else telemetry.endpoint_from(endpoint, env, configured)
        headers = telemetry.headers_from(env) or (credentials(telemetry.base_of(url)) if url and credentials else {})
        res = telemetry.resource(env, repo, version)
    except telemetry.PushError as exc:
        out(f"harness telemetry v2: {exc}")
        return 2
    state_path.parent.mkdir(parents=True, exist_ok=True)
    held = common._file_lock(state_path)
    try:
        held.__enter__()
    except OSError:
        out("harness telemetry v2: 다른 telemetry push가 실행 중이라 잠그지 못했다. 끝난 뒤 다시 실행한다")
        return 1
    try:
        return _send_locked(telemetry, collect, state_path, pricing, version, records, errors, url, headers, res,
                            dry_run, from_start, out, source_status or {})
    finally:
        held.__exit__(None, None, None)


def _send_locked(telemetry, collect, path, pricing, version, records, errors, url, headers, res, dry_run,
                 from_start, out, source_status) -> int:
    try:
        state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        errors += 1  # 상태를 잃어도 다시 만든 단위는 같은 ID라 중앙에서 중복 집계되지 않는다
        state = {}
    state = state if isinstance(state, dict) else {}
    if not isinstance(state.get("records"), dict):
        state["records"] = {}
    entries = state["records"]
    now = time.time_ns()
    oldest = now / 1e9 - RETENTION_SEC
    for rid, entry in list(entries.items()):
        if not isinstance(entry, dict) or not SAVED.issubset(entry) or not isinstance(entry["counts"], dict):
            del entries[rid]
            errors += 1
    pending = []
    for raw in records:
        moment = collect.parse_ts(raw["ts"])
        if moment is None or moment.timestamp() < oldest:
            continue
        rid = fingerprint([raw["tool"], raw["session"], raw["kind"], raw["key"]])
        old = entries.get(rid)
        material = materialize(raw, old, pricing, collect)
        material["id"] = rid
        signature = fingerprint(material)
        if old and old.get("signature") == signature and old.get("sent") and not from_start:
            continue
        material.update(signature=signature, sent=False)
        if not dry_run:
            entries[rid] = material
        pending.append(material)

    def save() -> None:
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, path)

    if dry_run:
        out(f"harness telemetry v2: 보낼 단위 {len(pending)}개, 원천 읽기 오류 {errors}. --dry-run이라 보내지 않는다")
        return 0
    save()  # 네트워크 전에 저장한다. 중단돼도 다음 실행이 같은 단가·ID로 다시 보낸다
    for rid, saved in list(entries.items()):  # 보낸 보관 기간 밖 단위만 지운다. 미전송 outbox는 보낼 때까지 남긴다
        stamp = collect.parse_ts(saved.get("ts"))
        if stamp is None or saved.get("sent") and stamp.timestamp() < oldest:
            del entries[rid]
    waiting = {record["id"]: record for record in pending}
    waiting.update({rid: record for rid, record in entries.items() if not record.get("sent")})
    values = list(waiting.values())
    for index in range(0, len(values), telemetry.BATCH):
        batch = values[index:index + telemetry.BATCH]
        try:
            rejected, _ = telemetry.send(url, headers, telemetry.payload(
                res, [log_record(record, telemetry, collect, now) for record in batch], version))
            if rejected:  # 같은 ID로 다시 보낸다. 중앙 쿼리가 ID별 최댓값을 쓰므로 중복 집계되지 않는다
                raise ValueError("partial_rejection")
        except (OSError, ValueError):
            state["failures"] = state.get("failures", 0) + 1
            state["last_attempt_unix"] = now // 10**9
            save()
            left = sum(not record.get("sent") for record in entries.values())
            out(f"harness telemetry v2: 전송 실패. 대기 {left}개는 다음 push에서 다시 보낸다(연속 실패 {state['failures']})")
            return 1
        for record in batch:
            entries[record["id"]]["sent"] = True
        save()
    health = {"harness.schema_version": SCHEMA, "harness.kind": "exporter", "session.id": "v2:exporter",
              "harness.event_unix": now // 10**9, "harness.last_success_unix": now // 10**9,
              "harness.previous_failures": state.get("failures", 0), "harness.pending": 0,
              "harness.source_errors": errors, "harness.agent_state": "unknown", "harness.delivery": "otlp_accepted",
              **{f"harness.source.{name}": status for name, status in source_status.items()}}
    log = {"timeUnixNano": str(now), "observedTimeUnixNano": str(now), "body": {"stringValue": "harness.v2.exporter"},
           "attributes": telemetry.attributes(health), "severityNumber": 9, "severityText": "INFO"}
    try:
        rejected, _ = telemetry.send(url, headers, telemetry.payload(res, [log], version))
        if rejected:
            raise ValueError("partial_rejection")
    except (OSError, ValueError):
        state["failures"] = state.get("failures", 0) + 1
        save()
        out("harness telemetry v2: 전송 상태 기록을 보내지 못했다. 사용량은 보냈다")
        return 1
    state.update(last_success_unix=now // 10**9, failures=0)
    save()
    out(f"harness telemetry v2: {len(values)}개 보냄, 원천 읽기 오류 {errors}")
    return 0 if errors == 0 else 1


def run(telemetry, common, collect, summary, target: Path, dirs: list[tuple[str, Path]], repo: str, pricing: dict,
        version: str, endpoint: str | None = None, env=None, dry_run: bool = False, from_start: bool = False,
        out=print, claude_home: Path | None = None, codex_home: Path | None = None, configured: str | None = None,
        credentials=None) -> int:
    """`telemetry push`의 v2 부분. dirs는 `telemetry.state_dirs`(첫 항목이 공용 git 디렉터리의 harness)."""
    env = os.environ if env is None else env
    roots = summary.worktree_paths(common, target)
    timelines = summary.branch_timelines(common, collect, roots)
    codex_path = Path(codex_home) if codex_home else collect.codex_home(env)
    # Claude Code 설정 홈. Claude Code와 같이 CLAUDE_CONFIG_DIR을 따른다
    claude_path = Path(claude_home or env.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    codex, codex_errors = codex_units(codex_path, roots, timelines, collect)
    claude, claude_errors = claude_units(claude_path, roots, collect, common)
    done, done_errors = completions(dirs, collect)
    # 원천 없음(not_found)·읽기 실패(error)·접근 가능(available). available도 에이전트가 실행 중이라는 뜻은 아니다
    status = {"codex": "error" if codex_errors else "available" if (codex_path / "sessions").is_dir() else "not_found",
              "claude": "error" if claude_errors else "available" if (claude_path / "projects").is_dir()
              else "not_found"}
    return send_records(telemetry, common, collect, repo, dirs[0][1] / STATE_FILE, pricing, version,
                        codex + claude + done, codex_errors + claude_errors + done_errors, endpoint, env, dry_run,
                        from_start, out, source_status=status, configured=configured, credentials=credentials)
