# 기여 규칙

키트 저장소는 GitHub에서 `main` 브랜치 하나로 운영한다. 루트 `AGENTS.md`의 공통 절차를 전제로,
이 저장소에만 해당하는 규칙을 정한다.

## 브랜치와 PR

- `main`에는 직접 Push하지 않고 PR로만 병합한다. 예외는 저장소 초기화 커밋뿐이다.
- 작업 브랜치 이름은 `<type>/<이슈번호>-<description>`이다. 예: `feat/12-judge-script`.
- 한 브랜치에는 GitHub 이슈 하나만 담는다. 이슈 제목에는 로드맵 번호(M1-5 등)를 붙인다.
- PR 본문은 `.github/PULL_REQUEST_TEMPLATE.md`를 채운다. 검증 절을 비워 두지 않는다.
- Squash merge를 사용하고 병합 후 브랜치를 삭제한다.
- 혼자 작업하는 동안에도 PR을 만든다. 리뷰어가 없으면 분리 세션의 AI 리뷰 결과를 본문에 붙인다.

## 커밋

Conventional Commits를 쓴다. Scope는 변경 영역이다.

| Scope | 변경 영역 |
| --- | --- |
| `templates` | `core/templates/` |
| `hooks` | `core/hooks/` |
| `ci` | `core/ci/`, `.github/workflows/` |
| `metrics` | `core/metrics/` |
| `profiles` | `profiles/` |
| `cli` | `bin/`, `tests/` |
| `docs` | `docs/`, `README.md` |

## 판정과 플랜·리뷰

키트는 백엔드 도메인이 아니라 스크립트와 문서이고, 주 안전망은 단위 테스트와 CI 리허설이다.
엄격 단계는 틀렸을 때 팀이 키트를 끄거나 거짓 안심을 주는 변경에만 둔다.

| 단계 | 조건 |
| --- | --- |
| 경량 | `docs/` 하위의 손으로 관리하는 문서, 주석, 테스트만 변경. 플랜 없이 판정과 근거를 시작 보고와 PR 본문에 남긴다 |
| 표준 | 그 밖의 변경(`bin/harness.py`, `core/templates/`, 보안 검사가 아닌 CI 조각 포함). 플랜·구현·리뷰 산출물을 한 세션에서 만든다 |
| 엄격 | `core/hooks/`의 차단·수정 로직 변경(오탐이 나면 팀이 hooks를 끈다), `core/ci/`의 보안 검사 조각 변경(틀려도 조용히 통과해 거짓 안심을 준다) |

첫 소비자 저장소에 적용한 뒤에는 `harness.json` 스키마, CLI 인자, 자리표시자 이름, 판정 식별자
(`lite`·`standard`·`strict`)를 깨는 변경도 엄격이다. 그 전에는 로드맵 M1-10의 적용 전 계약 리뷰에서
한 번에 본다.

엄격 단계는 플랜 승인과 분리 리뷰를 거친다. 플랜과 리뷰 파일은 루트 `plans/`에 두며 커밋하지 않는다.
양식은 `docs/templates/`를 따른다. 측정 칸을 비워 두지 않는다.

## 검증

```bash
python -m unittest discover tests -v
python bin/harness.py check --self
```

`core/templates/`를 고쳤으면 `python bin/harness.py init --self`로 자기 적용 파일을 다시 생성한 뒤 검증한다.
생성된 파일(`AGENTS.md`, `docs/templates/*`, `docs/adr/0000-template.md`, PR 템플릿 등)은 직접 고치지 않는다.

## 자기 적용에서 얻은 불편은 이슈로

키트를 쓰면서 절차를 건너뛰고 싶어지는 순간이 오면 그 이유를 `friction` 라벨 이슈로 남긴다.
이 기록이 다음 프로젝트 팀원이 만날 불편의 예고이자 측정의 시작이다.
