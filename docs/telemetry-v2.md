# 공통 텔레메트리 v2 (#140)

Claude Code와 Codex를 같은 사건 계약·가격표·사건 시각으로 비교하기 위한 키트 전송이다. 기존 원천(v1 키트 기록,
도구 내장 텔레메트리)과 함께 보내고 서로 더하지 않는다.

- 2026-10-21 사용자 합의: 기존 원천과 호환되는 v2를 추가하고 같은 가격표·사건 시각으로 두 도구를 비교한다. 운영 Loki의
  보관 정책은 바꾸지 않는다.
- 2026-10-23 사용자 합의(키트 0.4.0 반영): 주기 전송 프로세스(`telemetry watch`)는 두지 않는다. 실시간 사용 여부와 생존
  신호는 0.4.0의 도구 내장 텔레메트리(#145)가 맡고, v2는 사건이 있을 때 보낸다. Codex의 계기는 `Stop`(응답 종료)이다.

## 원천의 역할

| 원천 | 보내는 쪽·시점 | 저장소 귀속 | 비용 | 쓰는 곳 |
| --- | --- | --- | --- | --- |
| 공통 v2 | 키트 `telemetry push`(아래 전송 계기) | 있음 | 키트 가격표로 단위마다 고정 | `harness 팀 사용량`, 진단의 수집 상태 |
| v1 키트 기록 | 같은 push | 있음 | 기존 추정 | 진단(hooks), 접힌 원천 진단 |
| 도구 내장 텔레메트리 | 각 도구가 주기 전송(`telemetry setup`, #145) | 없음 | Claude만(구독 Codex는 없음) | 실시간 사용 여부, 내장 행 |

## 전송 계기

v2는 v1과 같은 `telemetry push` 한 번에 함께 나간다. 주소·인증도 같다(인자 → OTEL 변수 → `harness.json`의
`telemetry.endpoint`, 헤더 변수가 없으면 사용자 자격 파일). 따로 켜는 프로세스나 예약 작업은 없다.

| 도구 | 계기 | 설치 위치 |
| --- | --- | --- |
| Claude Code | `SessionEnd` hook | `.claude/settings.json` → `.claude/hooks/session-end.py` |
| Codex | `Stop` hook(마지막으로 띄운 뒤 5분이 지났을 때만), `SessionEnd` hook(보조, 항상) | `.codex/hooks.json` → `.claude/hooks/codex-hook.py` |
| 둘 다 | 수동 `python .harness/telemetry.py push` | — |

두 hook 모두 push를 백그라운드로 띄우고 바로 끝난다. 아무것도 출력하지 않고 실패해도 응답·종료를 막지 않는다.
`harness.json`에 `telemetry` 블록이나 OTEL 주소 변수가 없는 PC, `harness_events: false`면 띄우지 않는다. 여러 세션이 동시에
띄워도 전송 위치·잠금을 공유하므로 중복 전송되지 않는다.

Codex hook을 이렇게 정한 근거(2026-10-23, Windows, Codex 0.159~0.164 실측):

- 프로젝트 hook은 신뢰한 프로젝트의 `.codex/hooks.json`에서 읽는다. 처음 열 때 프로젝트 신뢰와 hook마다 승인을 묻고,
  승인은 명령의 해시로 사용자 `~/.codex/config.toml`에 남는다. **키트 갱신으로 명령이 바뀌면 다시 승인해야 한다.**
- `SessionStart`·`Stop`은 매번 왔다. stdin으로 `session_id`, `cwd`, `transcript_path`, `model`(Stop은 `turn_id`,
  `last_assistant_message`도)이 온다. hook 스크립트는 `cwd`만 읽는다.
- `SessionEnd`는 두 번 중 한 번만 왔다(`/exit`로 닫았는데도 오지 않았다). 그래서 주 계기로 쓰지 않는다.
- `codex exec`(비대화형)에서는 프로젝트 hook이 돌지 않았다. exec만 쓰는 환경은 수동 push나 다음 대화형 세션의 응답
  종료에 보낸다.
- Windows에서 명령은 PowerShell로 실행된다. 따옴표로 시작하는 명령(`"python.exe" ...`)은 PowerShell 문법 오류라
  `hooks.python`(`python`·`py`·`python3`) 다음에 `"$(git rev-parse --show-toplevel)/..."`를 둔다. PowerShell과 sh가 모두
  펼친다. 하위 디렉터리에서 열어도 worktree 루트를 찾는다.
- Orca·데스크톱 앱처럼 다른 실행 환경에서 hook이 도는지는 확인하지 않았다.

전송이 사건 시점보다 늦을 수 있으므로 화면은 사건 시각으로 집계한다(아래 "기간과 전환"). 마지막 전송이 오래됐다는
것만으로 수집이 끊겼다고 단정하지 않는다(진단 화면은 "24시간 전송 없음"으로 표시).

## 적용

1. 키트를 갱신하고 대상 저장소에 `python bin/harness.py init <대상-저장소> --force`. 기존 생성 파일 변경과 드리프트를 먼저
   확인한다. `.codex/hooks.json`, `.claude/hooks/codex-hook.py`, `.harness/metrics/normalized.py`가 새로 생긴다.
2. 팀원 PC 설정은 0.4.0과 같다(`python .harness/telemetry.py setup`, `doctor`). 추가 설정은 없다.
3. Codex를 저장소에서 처음 열면 프로젝트 신뢰와 hook 두 개(`Stop`, `SessionEnd`)를 승인한다.
4. `python .harness/telemetry.py push --dry-run`으로 보낼 v1 기록과 v2 단위 수를 본다. 첫 실행은 이 PC에서 읽을 수 있는
   최근 7일 원천만 복원한다.

기존 대시보드 `harness-agentops`는 v1·내장 원천을 계속 보여 준다. **harness 팀 사용량**(`harness-agentops-normalized`)은
v2만 읽는다. 전환 전 수치와 새 수치를 합산하지 않는다. Claude 네이티브 OTEL 비용은 진단용이며 공통 비용에 더하지 않는다.
갱신 전 키트는 v2를 보내지 않으므로 대시보드만 추가해서는 팀원 PC의 수집 조건이 같아지지 않는다.

## 사건 계약

| 속성 | 정의 |
| --- | --- |
| `harness.schema_version` | 2. 기존 v1 session/hook 로그는 유지 |
| `harness.kind` | `usage` / `completion` / `exporter` |
| `member` | 기존 인증 프록시가 결정. 클라이언트가 새 사람 식별자를 만들지 않음 |
| `harness.repo` / `harness.tool` / `model` | 저장소·도구(`claude-code`, `codex`)·모델 |
| `harness.session` / `harness.parent` / `harness.branch` | 원천 세션·부모·사건 시점 브랜치 |
| `harness.record_id` | 도구·세션·사건 종류·원천 단위 ID의 SHA256. 재시도/다른 worktree에서 고정 |
| `harness.event_unix` / `harness.day` | 원천 usage 사건 초 / KST 날짜 |
| `timeUnixNano` / `observedTimeUnixNano` | 전송 시각. Loki의 과거 스트림 순서 제한으로 지연 전송을 잃지 않게 함 |
| `session.id` | Loki 스트림을 기존 로그와 분리하는 `v2:` 접두의 세션. 실제 세션은 `harness.session` |
| `harness.tokens.*` | input(캐시 제외), output, cache_read, cache_write_5m, cache_write_1h |
| `harness.price_id` / `harness.price_as_of` / `harness.currency` | 적용 가격표 해시·기준일·통화 |
| `harness.cost_status` | `priced` / `unpriced`. 여러 단위 중 미등록이 있으면 화면 합계는 부분 비용 |
| `harness.cost_estimate` | 단가가 확인된 단위의 추정액. 미등록이면 필드 자체를 보내지 않음 |
| `harness.unpriced_tokens` | 단가가 없어 비용에서 제외된 토큰. 명시적 0원 단가와 다름 |
| `harness.attribution` | `request` / `legacy-first` / `legacy-delta` / `legacy-reset` |
| `harness.delay_seconds` | 전송 시각과 사건 시각의 차이. 과거 비용을 전송일로 옮기지 않음 |
| `harness.completed` / `harness.verify` | 완료 사건 1 / 검증 결과. 사용량 사건과 별개 |

Claude의 API 메시지 ID별 스트리밍 usage는 필드별 최댓값 한 번만 센다. 각 메시지의 최초 유효 usage 시각을 고정한다.
서브에이전트 파일은 독립 세션으로 읽으므로 부모 누적에 다시 더하지 않는다. 완료 응답은 키트 Claude Stop 기록이며
서브에이전트는 완료 응답에 포함하지 않는다. 아직 hooks를 설치하지 않은 Claude의 완료 응답은 미수집이다. Claude Code
설정 홈은 `CLAUDE_CONFIG_DIR`(없으면 `~/.claude`)이고 `push --claude-home`으로 바꿀 수 있다.

Codex는 `token_usage_record` 한 줄을 청구 단위로 삼고, `task_complete`를 부모 응답 완료로 센다. 모델 전환은 각 단위의
당시 모델에 반영한다. 브랜치는 HEAD reflog와 기존 수집기의 기준을 공유한다. 진행 중 usage를 보낸 뒤 완료돼도 같은 토큰을
다시 보내지 않는다. 하위 세션은 비용/토큰만 포함하고 응답 수에서는 제외한다.

옛 Codex의 `token_count` 누적 형식은 증가분으로 나눈다. 최초 기준이 없으면 `legacy-first`로 명시하며 그 이전 소비가 첫
사건에 포함될 수 있다. 누적 감소는 `legacy-reset`으로 분리한다. 이 과거 형식을 API 요청 단위만큼 정확한 시각 귀속으로
해석하지 않는다.

두 도구 모두 원천의 청구 단위별 토큰 스냅샷을 전송한다. 중앙 쿼리는 기록 ID별 최댓값을 구한 뒤 합산해 재시도·스트리밍
갱신·복구에 따른 중복을 없앤다. 토큰은 음수/역방향 갱신으로 줄이지 않는다. 완료 사건은 별도 ID여서 사용량을 다시 더하지
않는다. 단가와 차원은 최초 전송 준비 시 저장하며 반복 전송/가격 설정 변경에도 그대로 쓴다.

## 기간과 전환

공통 쿼리는 **조회 종료 시점까지 수신된 로그**에서 사건 시각이 선택 기간에 속한 단위를 집계한다. 일별 비용도 사건의
KST 날짜를 사용한다. 전송이 늦으면 조회 종료를 현재로 둔 화면에서 과거 날짜가 보완된다. 과거로 고정한 종료 시점은 그
시점 이후 도착한 내용을 포함하지 않는 당시 관측값이다.

보관·조회 지원 범위는 7일이다. 7일보다 오래된 원천 사건은 새로 전송하지 않는다. Loki는 전송 시각으로 보관하고 화면은
사건 시각으로 거른다. 7일 넘게 push하지 않은 PC의 그 이전 사용량은 보내지 않는다. 수집하지 못했던 완료/검증 사건을
만들어 내지 않는다.

가격 기준의 캐시를 포함한 outbox는 공용 Git 디렉터리 `harness/telemetry-v2.json`이다. 기존 `telemetry.json`과 분리한다.
네트워크 전 저장하고 성공한 묶음만 완료 표시한다. 실패·부분 거절은 같은 ID로 다음 push에서 재시도한다. v1의 기존 부분
거절 정책은 바꾸지 않는다. 이미 전송한 기간 밖 상태는 정리하지만 미전송 outbox는 복구까지 남긴다. 상태 파일을 지우거나
잃으면 적용 가격 캐시를 복원할 수 없다. 재생성된 기록은 ID로 중복 제거되지만 가격은 그때의 가격표로 다시 고정된다.

## 상태 해석

- `pass`, `fail`, `cached-pass`, `cached-fail`, `not-run`, `unsupported`, `unknown`을 구분한다. Claude `none`은 not-run,
  오류/누락은 unknown이다.
- Codex 네이티브 검증/승인과 공통 hook 차단은 **미지원**이다. Codex `Stop` hook은 전송 계기로만 쓰고 검증을 실행하지
  않는다. Codex 완료 사건에는 실행 결과를 연결할 계약이 없으므로 성공으로 채우지 않고 unsupported로 둔다.
- exporter 사건은 push마다 마지막 성공 시각·이전 전송 실패 수·원천 읽기 오류·원천 상태를 보고한다. 실패 중에는 로컬
  outbox/오류 출력에 남기고 복구 후 중앙에 알린다.
- 진단 화면의 수집 상태는 마지막 v2 전송 시각이다. 24시간 전송 없음은 도구를 쓰지 않은 경우도 포함한다. 지금 쓰고
  있는지는 도구 내장 텔레메트리로 보고, 키트 전송만으로 에이전트 실행 상태를 추정하지 않는다(`harness.agent_state`는 항상
  `unknown`).
- OTLP 수락과 Loki 최종 저장은 다르다. 서버 도착 목록에 한 번도 나타나지 않은 PC는 중앙에서 목록 자체를 알 수 없다.
- 원천 디렉터리 없음은 `not_found`, 관련 파일 읽기 실패는 `error`, 접근 가능은 `available`이다. available도 에이전트
  실행 중을 뜻하지 않는다. 소속을 판정할 수 없는 다른 저장소 파일은 해당 저장소의 오류로 세지 않는다.

프롬프트·응답 본문·코드·transcript 경로·인증정보는 전송/상태 파일에 추가하지 않는다. 기본 로컬 홈 아래 파일에서 허용된
ID·시각·토큰 필드만 추출한다.

## 검증

`tests/test_normalized.py`가 두 도구 동등 입력, 모델·스트리밍·하위 세션, 명시적 0원/미등록, 재전송·재시작·실패/부분
거절, 기간 경계·리셋, 0.4.0 주소·자격 파일 해석, push 한 번의 v1→v2 순서, Codex hook의 간격·조용한 실패를 검사한다.
CI `observability` job은 기존 스모크에 이어 `.github/scripts/normalized_smoke.py`로 실제 Loki에서 중복·진행 갱신·지연 날짜
귀속·필터 및 팀 사용량 대시보드의 모든 쿼리를 확인한다. 이 스크립트는 기록을 전송하므로 운영에서 실행하지 않는다.
