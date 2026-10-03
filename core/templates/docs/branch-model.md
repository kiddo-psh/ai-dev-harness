# 브랜치 모델별 문서 조각

`docs/git-convention.md`·`docs/development-workflow.md`에서 브랜치 모델에 따라 달라지는 절이다. 매니페스트 `includes`가
`when`으로 골라 넣는다: `two-branch`는 `integration_branch`(예: `develop`)와 `default_branch`가 다를 때, `trunk`는 둘이
같을 때(통합 브랜치 없이 `main`에 직접 병합). 같은 이름의 두 변형을 모두 둬야 한다.

## Git 운영 원칙 · 두 브랜치

- `{{default_branch}}`은 배포 및 시연 가능한 안정 버전을 유지한다.
- `{{integration_branch}}`은 팀 개발 내용을 지속적으로 통합하는 기본 브랜치다.
- 실제 개발은 {{issue_noun}} 단위의 짧은 작업 브랜치에서 진행한다.
- `{{default_branch}}`과 `{{integration_branch}}`에는 직접 Push하지 않고 {{pr_long}}를 통해서만 병합한다.
- 영역별 장기 통합 브랜치는 만들지 않는다.

```text
{{default_branch}}
  ↑  팀 합의 일정에 따라 QA 및 통합 테스트 후 병합
{{integration_branch}}
  ↑        ↑        ↑
feat/*    fix/*    refactor/*
```

## Git 운영 원칙 · 단일 브랜치

- 브랜치는 `{{default_branch}}` 하나와 {{issue_noun}} 단위의 짧은 작업 브랜치만 둔다. 통합 브랜치(`develop`)와 영역별 장기
  브랜치는 만들지 않는다.
- `{{default_branch}}`은 통합 브랜치이자 기본 브랜치다. 항상 빌드·검증이 통과하고 배포·시연 가능한 상태를 유지한다.
- `{{default_branch}}`에는 직접 Push하지 않고 {{pr_long}}를 통해서만 병합한다.
- 릴리스·시연 시점은 `{{default_branch}}`의 커밋에 태그로 표시한다(4장).

```text
{{default_branch}}  ──●──────●──────●──▶   (태그: 릴리스·시연 시점)
                      ↑      ↑      ↑
                   feat/*  fix/*  refactor/*   (짧은 작업 브랜치, {{pr_noun}}로 병합)
```

## Git 브랜치 표 · 두 브랜치

| 브랜치 | 역할 |
| --- | --- |
| `{{default_branch}}` | 배포 및 시연 가능한 안정 버전 |
| `{{integration_branch}}` | 팀 개발 결과가 합쳐지는 통합 브랜치이자 기본 브랜치 |
| 작업 브랜치 | 하나의 {{issue_noun}}을 구현하는 단기 브랜치 |

## Git 브랜치 표 · 단일 브랜치

| 브랜치 | 역할 |
| --- | --- |
| `{{default_branch}}` | 통합 브랜치이자 기본 브랜치. 항상 배포·시연 가능한 상태 |
| 작업 브랜치 | 하나의 {{issue_noun}}을 구현하는 단기 브랜치. 최신 `{{default_branch}}`에서 만들고 `{{default_branch}}`으로 병합 |

## Git 릴리스 절 · 두 브랜치

### {{integration_branch}}에서 {{default_branch}}으로 병합

- 팀장이 팀 합의 일정에 따라 통합 {{pr_noun}}을 진행한다.
- QA와 통합 테스트를 통과한 `{{integration_branch}}`만 `{{default_branch}}`으로 병합한다.
- 예정된 통합일이라도 빌드·테스트가 실패하거나 시연 가능한 상태가 아니면 병합을 보류한다.
- 통합 {{pr_noun}}에는 {{issue_key}}를 제목에 강제하지 않는다.
- 생성 시 `Release.md` 템플릿을 직접 선택한다.
- Squash를 사용하지 않고 Merge commit을 생성해 업무 단위 커밋 이력을 유지한다.

## Git 릴리스 절 · 단일 브랜치

### 릴리스 태그

통합 브랜치가 없으므로 릴리스는 `{{default_branch}}`의 특정 커밋에 태그를 다는 것이다. 통합 {{pr_noun}}은 없다.

- 태그 이름과 시점(예: `release/<버전>`, 시연 전날)은 프로젝트가 정해 이 절에 적는다.
- 태그는 팀장이 `{{default_branch}}`에서 붙이고 Push한다. 태그 커밋은 영역 검증 명령이 모두 통과한 상태여야 한다.
- 릴리스 직전 급한 수정도 작업 브랜치 → {{pr_noun}} → `{{default_branch}}` 순서를 지키고, 병합 뒤 **새 태그**를 붙인다
  (예: 패치 번호를 올린 이름). 이미 Push한 태그는 옮기지 않는다(강제 갱신이 필요하고 다른 클론에는 예전 값이 남는다).
  태그 커밋에 직접 커밋하지 않는다.
- 릴리스 범위, 환경 변수·DB 변경, 롤백 방법은 태그를 붙이기 전에 팀 채널에 남긴다. `Release.md` {{pr_noun}} 템플릿은
  쓰지 않는다.

## 개발 흐름 통합 단계 제목 · 두 브랜치

{{integration_branch}}에서 {{default_branch}}으로 통합

## 개발 흐름 통합 단계 제목 · 단일 브랜치

릴리스 태그

## 개발 흐름 통합 단계 · 두 브랜치

1. 팀 합의 일정에 따라 QA와 통합 테스트를 수행한다.
2. 실패한 빌드나 테스트가 있으면 `{{default_branch}}` 병합을 보류한다.
3. `{{integration_branch}}`에서 `{{default_branch}}`으로 {{pr_noun}}을 생성한다.
4. 생성 화면에서 `Release.md` 템플릿을 직접 선택한다. 대상 브랜치만으로 자동 선택되지 않는다.
5. 릴리스 범위, 주요 변경, 환경 변수, DB 변경 및 롤백 방법을 확인한다.
6. Squash를 해제하고 Merge commit을 생성해 병합한다.

통합 {{pr_noun}}은 팀장이 진행하며, 구체적인 주기는 팀 합의로 정한다.

## 개발 흐름 통합 단계 · 단일 브랜치

통합 브랜치가 없으므로 별도의 통합 {{pr_noun}}은 없다. 릴리스·시연은 `{{default_branch}}`의 커밋에 태그로 표시한다
(태그 이름과 시점은 Git 컨벤션 4장).

1. `{{default_branch}}`를 최신화한다. 이 뒤로는 pull하지 않는다.

```bash
git switch {{default_branch}}
git pull --ff-only origin {{default_branch}}
git rev-parse HEAD   # 검증하고 태그를 붙일 커밋
```

2. 그 커밋에서 영역 검증 명령을 모두 돌려 통과를 확인한다.
3. 릴리스 범위, 환경 변수·DB 변경, 롤백 방법을 팀 채널에 적는다.
4. 팀장이 1단계에서 확인한 커밋에 태그를 붙이고 Push한다. 그 사이 원격에 새 커밋이 병합됐으면 1단계부터 다시 한다.

```bash
git tag -a <태그> <검증한 커밋> -m "<릴리스 설명>"
git push origin <태그>
```

5. 릴리스 직전 급한 수정도 작업 브랜치 → {{pr_noun}} → `{{default_branch}}` 순서를 지키고, 병합 뒤 위 절차로 **새 태그**
   (예: 패치 번호를 올린 이름)를 붙인다. 이미 Push한 태그는 옮기지 않는다. 태그 커밋에 직접 커밋하지 않는다.
