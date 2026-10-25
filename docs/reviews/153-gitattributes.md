# #153 init이 루트 .gitattributes(LF 강제)를 설치 — 리뷰

2026-10-25. 대상: `feat/153-gitattributes`, 기준 커밋 `980ef3d`, 커밋 `189599c`(W1, 작성 세션과 같은 세션).

## 1. 읽기 범위

| # | 변경 단위 | 파일 | 참조한 계약 절 |
| --- | --- | --- | --- |
| U1 | 템플릿·매니페스트 | `core/templates/.gitattributes`, `core/templates/manifest.json` | 매니페스트 `seed` 설명, `docs/git-convention.md` 5장 |
| U2 | 문서 | `docs/install.md`, `docs/first-day.md` | install.md 2·4·10·13절 |
| U3 | 테스트 | `tests/test_harness.py` `SeedFileTest` | 시드 파일 계약 |

## 2. 테스트 실효성

| 플랜 # | 실제 테스트 | 대응 | 기대값 변경 기록 확인 |
| --- | --- | --- | --- |
| 생성 | `SeedFileTest.test_gitattributes_seeded_with_lf` | 매니페스트 항목이 없으면 파일이 없어 실패 | 없음 |
| 보존 | `SeedFileTest.test_existing_gitattributes_is_kept` | `init`·`init --force` 뒤 기존 내용 유지 | 없음 |

## 3. 발견 사항

### F1 — 키트 저장소 안의 `core/templates/.gitattributes`가 그 디렉터리의 git 속성으로도 적용된다
- 단위 / 관점: U1 / 정확성
- 근거: git은 하위 디렉터리의 `.gitattributes`도 읽는다. 내용이 루트 `.gitattributes`와 같은 규칙(LF, 배치 CRLF, 바이너리)이다.
- 영향과 제안: 참고. 루트와 같은 규칙이라 실제 동작은 바뀌지 않는다. 이후 템플릿에 루트와 다른 규칙을 넣을 때는 키트 자신의 `core/templates/` 파일에도 적용된다는 점을 고려한다.

### F2 — 기존 저장소에 설치하면 CRLF 파일이 수정된 것으로 보일 수 있다
- 단위 / 관점: U2 / 회귀 위험
- 근거: `* text=auto eol=lf`가 생기면 CRLF로 커밋된 텍스트 파일이 정규화 대상이 된다.
- 영향과 제안: 낮음. install.md 4절에 줄끝만 바꾸는 별도 커밋(`git add --renormalize .`) 안내를 넣었다.

## 5. 단위 간 정합성 (마지막 1회)

- 계약: 시드 파일 계약(처음만 생성, `--force` 비덮어쓰기, `check`는 존재만)을 그대로 따른다. `self: false`라 키트 자기 적용은 바뀌지 않는다.
- 트랜잭션 경계: 해당 없음
- 오류 코드: 해당 없음

## 6. 측정 칸 (비워 두지 않는다)

| 항목 | 값 |
| --- | --- |
| 읽은 기준 문서 절 수 | 2 |
| 열린 조건부 관점 (동시성·트랜잭션 / 인가) | 닫힘 / 닫힘 |
| 발견 사항 수 (참고 제외 / 참고) | 1 / 1 |
| 리뷰 세션 모델 | claude-opus-5-5 |
| PR 리뷰에서 뒤늦게 발견된 누락 (병합 후 기입) | (병합 후 기입) |

## 7. 처리 (작성자가 반영 뒤 채운다)

플랜 승인: 해당 없음

| # | 결함 | 심각도 | 발견 | 처리 | 근거 |
| --- | --- | --- | --- | --- | --- |
| 1 | 하위 `.gitattributes`가 키트의 템플릿 디렉터리에도 적용 | 참고 | F1 | 기각: 루트와 같은 규칙이라 동작 변화 없음 | 내용 비교 |
| 2 | 설치 뒤 CRLF 파일 정규화 diff | 낮음 | F2 | 채택: install.md 4절 정규화 커밋 안내 | 같은 PR 커밋 189599c |
