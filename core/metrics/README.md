# core/metrics

키트의 효과를 숫자로 보이는 수집기. 로드맵 M2-6(CI 실패 분류)과 M4-1·M4-2에서 채운다.

수집하는 지표 (roadmap 1장)

| # | 지표 | 출처 |
| --- | --- | --- |
| 1 | 병합 후 발견된 누락 수 | 리뷰 파일 측정 칸 → MR 본문 "검증" 절 |
| 2 | 엄격 단계 MR 비율 | 플랜 상단 판정 → MR 본문 |
| 3 | CI 실패 원인 분류 | job 로그 규칙 분류 (`classify_ci.py`, `harness classify-ci`) |
| 4 | 판정 스크립트와 사람 판정의 불일치 수 | `harness judge` 출력과 플랜 판정 대조 |

예정 내용: `collect.py`(MR 본문·CI API에서 JSON 추출), `notify.py`(주간 요약 webhook 발송,
feelm Jira 일일 요약 발송 코드 이관).

## CI 실패 원인 분류 (`classify_ci.py`)

이미 끝난 파이프라인의 job 메타데이터와 trace 파일을 읽어 실패 원인 범주를 정하는 순수 분류기다.
네트워크로 수집하지 않는다. 수집은 아래 어댑터 명령으로 파일을 만든 뒤 넘긴다.
M4-1 수집기도 이 모듈을 import해 쓴다.

```bash
python bin/harness.py classify-ci --jobs jobs.json --trace-dir traces/ --out ci-failures.jsonl
```

입력

- `--jobs`: GitLab job API 형태의 job 객체 목록(`id`·`name`·`stage`·`status`·`failure_reason`). 단일 객체,
  한 줄에 객체 하나(JSONL), 페이지별 배열을 이어 붙인 출력도 읽는다. `id`(정수)와 `status`는 필수다.
- `--trace-dir`: `<job_id>.log` 파일이 있는 디렉터리. 파일이 없는 job은 메타데이터만으로 분류한다.
- `status`가 `failed`인 job만 분류한다. 성공·취소·건너뜀 등은 산출에서 빼고 개수만 stderr에 적는다.

산출 (`--out` 생략 시 표준 출력): job 하나당 JSON 한 줄. 집계는 하지 않는다(M4-1).

```json
{"job_id": 12, "name": "backend-test", "stage": "test", "failure_reason": "script_failure", "category": "format",
 "matches": [{"rule": "test.gradle", "category": "test", "line": 5, "count": 4},
             {"rule": "format.spotless", "category": "format", "line": 7, "count": 3}]}
```

`category`는 `test`·`format`·`infra`·`timeout`·`security`·`unclassified` 중 하나다. `matches`에는 판정에 쓰지
않은 규칙까지 일치한 규칙을 모두 남긴다(`line`은 첫 일치 줄 번호, 메타데이터 규칙이면 `null`, `count`는 일치한 줄 수).

판정 순서 — 앞 단계에서 정해지면 뒤 단계는 `matches`에만 남는다.

1. `failure_reason`: `job_execution_timeout`·`stuck_or_timeout_failure` → `timeout`, `runner_system_failure`·`api_failure` 등
   runner·플랫폼 오류 → `infra`. `script_failure`·`unknown_failure`는 원인을 정하지 않는다.
2. 구조화 표식: trace의 `<NAME>_RESULT={"category": "..."}` JSON 한 줄. 지금 키트 CI 조각은 이 표식을 출력하지 않는다.
3. job 이름: `harness-`로 시작하면(키트 보안 검사 job) `security`
4. 로그 정규식: GitLab 실행 시간 초과 문구 → 인프라(DNS·네트워크·이미지 pull·OOM·디스크·runner) → 포맷(Spotless·Prettier·
   ESLint·Black/Ruff·Checkstyle/ktlint) → 테스트(Gradle·Maven·Jest/Vitest·pytest·unittest·Go)

규칙은 `classify_ci.py`의 `REASON_CATEGORIES`·`LOG_RULES`에 코드로 둔다. 규칙을 바꾸면
`tests/test_classify_ci.py`에 합성 로그 fixture(`tests/fixtures/classify_ci/`)를 함께 추가한다.
fixture에는 Secret·실제 호스트명·IP·프로젝트명을 넣지 않는다.

### 수집 어댑터 (참고 명령)

분류기는 아래 명령의 출력 파일만 읽는다. 명령은 저장소 디렉터리에서 실행하며, 토큰은 각 CLI의 로그인 상태를 쓴다.

GitLab (`glab`, `:id`는 현재 저장소로 바뀐다)

```bash
glab api --paginate "projects/:id/pipelines/<pipeline_id>/jobs?per_page=100" > jobs.json
mkdir -p traces
for id in <실패한 job id ...>; do
  glab api "projects/:id/jobs/$id/trace" > "traces/$id.log"
done
```

GitHub Actions (`gh`, `failure_reason`·`stage`가 없어 로그와 job 이름으로만 분류된다)

```bash
gh api --paginate "repos/{owner}/{repo}/actions/runs/<run_id>/jobs" \
  --jq '.jobs[] | {id, name, stage: null, failure_reason: null,
                   status: (if .conclusion == "failure" then "failed" else (.conclusion // .status) end)}' > jobs.json
mkdir -p traces
for id in <실패한 job id ...>; do
  gh api "repos/{owner}/{repo}/actions/jobs/$id/logs" > "traces/$id.log"
done
```
