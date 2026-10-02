# 설치 가이드

이 문서는 ai-dev-harness를 대상 저장소에 붙이고, 확인하고, 끄고, 걷어내는 절차를 다룬다.
키트 자신에게 적용하는 절차(자기 적용)는 [README](../README.md)에 있다.

목표는 빈 저장소에 키트를 붙여 첫 병합 요청이 엄격 단계 절차까지 통과하는 데 반나절을 넘기지 않는
것이다([개발 계획](roadmap.md) 1장).

## 1. 준비물

- Python 3.12 이상. 키트는 표준 라이브러리만 쓰므로 설치할 의존성이 없다
- git
- 키트 저장소를 clone해 둔다. 대상 저장소와 별도 디렉터리에 둔다

```bash
git clone https://github.com/kiddo-psh/ai-dev-harness.git
cd ai-dev-harness
python bin/harness.py version
```

`init`은 clone한 키트 디렉터리에서 실행하고 대상 저장소 경로를 인자로 준다. 키트를 대상 저장소 안에
복사하지 않는다.

## 2. 무엇이 설치되는가

생성 목록은 `core/templates/manifest.json`이 정의한다. 플랫폼(`gitlab`·`github`)에 따라 병합 요청
템플릿의 경로가 달라진다.

| 대상 | 내용 |
| --- | --- |
| `AGENTS.md`, `CLAUDE.md` | AI 도구가 따르는 공통 절차 |
| `docs/README.md` | 문서 역할과 우선순위 |
| `docs/ai-collaboration.md` | AI 병렬 작업과 충돌 방지 |
| `docs/git-convention.md` | 브랜치·커밋·병합 요청 |
| `docs/development-workflow.md` | 업무 시작부터 병합까지 |
| `docs/secret-environment-variables.md` | Secret과 환경 변수 |
| `docs/templates/plan.md`, `docs/templates/review.md` | 플랜·리뷰 양식 |
| `docs/adr/README.md`, `docs/adr/0000-template.md` | 설계 결정 기록 |
| `.gitlab/merge_request_templates/` 또는 `.github/PULL_REQUEST_TEMPLATE.md` | 병합 요청 본문 |
| `.claude/settings.json`, `.claude/hooks/` | Claude Code hooks ([설명](../core/hooks/README.md)) |
| `harness.json` | 대상 저장소의 키트 설정. 이후 모든 명령이 이 파일을 읽는다 |
| `.harness/claude-review/` | `harness.json`에 `claude_review` 블록이 있을 때만. Claude MR 리뷰 스크립트와 시스템 프롬프트(14절) |

영역 `AGENTS.md`는 3절에서 따로 생성한다. GitLab CI 조각은 5절에서 연결한다.

## 3. 새 저장소에 붙이기

### 3.1 루트 생성

```bash
python bin/harness.py init ../my-project \
  --project-name my-project \
  --platform gitlab \
  --tracker jira \
  --issue-prefix ABC123 \
  --default-branch main \
  --integration-branch develop
```

| 인자 | 기본값 | 설명 |
| --- | --- | --- |
| `--project-name` | 대상 디렉터리 이름 | 문서에 들어갈 프로젝트 이름 |
| `--platform` | `gitlab` | `gitlab` 또는 `github`. 병합 요청 템플릿 경로와 MR·PR 용어를 정한다 |
| `--tracker` | `jira` | `jira` 또는 `github`. 업무 항목 용어와 이슈 키 예시를 정한다 |
| `--issue-prefix` | 없음 | Jira 프로젝트 키. **`--tracker jira`이면 필수다** |
| `--default-branch` | `main` | |
| `--integration-branch` | `develop` | 통합 브랜치를 쓰지 않으면 `main`과 같게 준다 |

대상 디렉터리가 없으면 만든다. 생성한 파일 목록이 출력된다.

### 3.2 영역 생성

영역은 담당자와 검증 명령이 갈리는 단위다(`backend`, `frontend` 등). 루트 `init` 다음에 실행한다.

```bash
python bin/harness.py init ../my-project --area backend \
  --verify-cmd "./gradlew test" \
  --verify-cmd "./gradlew ktlintCheck" \
  --area-doc "docs/api/openapi.yaml"
```

- `--verify-cmd`는 **하나 이상 필수**다. 반복해서 여러 개를 줄 수 있다. 파일을 고치지 않는 명령만 적는다
- `--trigger`, `--review-focus`는 생략하면 키트 기본값을 쓴다. 주면 기본값을 **대체**한다(추가가 아니다)
- `--area-doc`은 그 영역의 기준 문서다. 준 것만 적힌다. 여기 적은 경로는 hooks가 `ask`로 보호한다
- `--area`는 대상의 `harness.json`을 쓰므로 `--platform` 같은 루트 인자와 함께 쓸 수 없다
- 경로는 대상 저장소 기준 상대 경로다. `./web/`처럼 줘도 `web`으로 정규화된다. 절대 경로와 `..`는 거부한다
- 같은 `--area`를 다시 실행하면 `harness.json`의 해당 항목을 제자리에서 바꾼다. 다만 이미 있는
  `<영역>/AGENTS.md` 파일은 `--force` 없이 덮어쓰지 않는다. 생략한 trigger·review focus·문서는 이전 값을 유지한다

결과로 `<영역>/AGENTS.md`가 생기고 `harness.json`의 `areas`에 설정이 기록된다. 판정용 경로 규칙
`trigger_paths`·`test_paths`(아래 3.4)도 키트 기본값으로 함께 기록된다. 바꾸려면 `harness.json`을 직접 고친다.

### 3.3 첫 커밋

```bash
cd ../my-project
git add .
git commit -m "chore: ai-dev-harness 적용"
```

`.claude/settings.json`과 `.claude/hooks/`는 **커밋한다**. 팀 전체가 같은 가드레일을 쓰기 위해서다.
개인 설정은 `.claude/settings.local.json`에 두고 이 파일은 커밋하지 않는다.

### 3.4 판정 확인 (`harness judge`)

작업 브랜치의 변경 파일로 경량·표준·엄격(`lite`·`standard`·`strict`)을 산출한다. 기계 판정은 하한이다.
사람이 판정을 올릴 수는 있어도 내리지 않는다.

```bash
python bin/harness.py judge ../my-project                       # origin/<default_branch>와의 merge-base 이후
python bin/harness.py judge ../my-project --base origin/develop --json
git diff --name-only origin/main | python bin/harness.py judge ../my-project --files -
```

- 변경 파일은 merge-base 이후 커밋, 커밋하지 않은 수정, 추적 안 된 파일이다. 이름을 바꾼 파일은 옛 경로와 새 경로를 모두 본다
- 파일마다 `trigger_paths.strict` → `trigger_paths.standard` → 문서(`*.md`, 루트 `docs/`) → `test_paths` 순으로 맞춰
  보고, 어디에도 안 맞으면 표준이다. 전체 판정은 가장 높은 값이다. 문서·테스트만 바뀌었으면 경량이다
- 패턴은 gitignore 방식이고 영역 디렉터리 기준이다(`/src/auth/`는 `<영역>/src/auth/` 아래). 영역 밖 파일은
  최상위 `judge`의 `trigger_paths`·`test_paths`(저장소 루트 기준)를 쓴다. 기본값은 키 단위로 대체된다. `trigger_paths`를
  지정하지 않은 곳에는 공통 기본(lock 파일·CI 정의·DB 마이그레이션 → 엄격)을, `test_paths`를 지정하지 않은 곳에는 기본
  테스트 경로를 쓴다
- 최상위 `judge.triggers`는 영역 밖 파일이 하나라도 바뀌면 출력된다. 문서만 바꿔도 나오므로 문장은 조건을 담아 쓴다
- 영역의 `triggers`와 최상위 `judge.triggers` 문장(계약 불일치, 인가 등)은 경로로 판정할 수 없어 "사람 확인 필요"로만
  출력한다
- `--files` 목록은 UTF-8(BOM 허용) 한 줄에 경로 하나다. `git diff --name-only`가 따옴표로 감싼 비ASCII 경로도 풀어 읽는다
- 판정과 무관하게 종료 코드 0이다. 설정·git 오류는 2

## 4. 기존 저장소에 붙이기

기존 파일을 말없이 덮어쓰지 않는다. 충돌하는 파일이 하나라도 있으면 **아무것도 쓰지 않고 중단**하고
목록을 보여 준다.

```
오류: 이미 존재하는 파일이 있어 중단한다. 덮어쓰려면 --force 를 지정한다:
  AGENTS.md
  docs/README.md
```

권장 순서는 다음과 같다.

1. **먼저 깨끗한 작업 트리에서 시작한다.** 커밋하지 않은 변경이 있으면 커밋하거나 stash한다
2. 위 목록을 보고 각 파일을 어떻게 할지 정한다
   - 기존 내용이 없어도 되면 → `--force`
   - 기존 내용을 살려야 하면 → 생성 파일을 덮어쓰기 전에 별도 브랜치에서 내용을 검토한다. 특히 기존
     `.claude/settings.json` 병합은 아직 지원하지 않는다. 수동 병합 파일은 `check`에서 드리프트로 표시된다
3. `--force`로 실행한다. `harness.json`이 아직 없다면 필요한 루트 인자도 함께 준다

```bash
# 기존 harness.json이 있는 경우
python bin/harness.py init ../my-project --force

# 기존 harness.json이 없는 GitHub 저장소의 예
python bin/harness.py init ../my-project --force --platform github --tracker github
```

4. `git diff`로 무엇이 바뀌었는지 확인한 뒤 커밋한다

### 주의할 점

- **`--force`는 생성 대상 파일만 덮어쓴다.** `harness.json`도 다시 쓰지만 기존 파일을 읽어서 쓰므로
  `hooks`, `areas` 같은 설정은 보존된다. 바뀌는 것은 `harness_version`이 키트 버전으로 맞춰지는 것과
  들여쓰기·키 순서뿐이다
- **`harness.json`이 이미 있으면 `--platform`·`--tracker` 같은 루트 인자를 함께 쓸 수 없다.** 값을
  바꾸려면 `harness.json`을 직접 고치고 `init --force`로 다시 생성한다. `--config`와 루트 인자도 함께 쓸 수 없다
- **부분 적용은 지원하지 않는다.** 일부 파일만 생성하는 인자는 없다. 필요 없는 파일은 생성 후 지우면
  되지만, 그러면 `check`가 "없음"으로 보고한다(8절)

## 5. CI 조각

보안 검사 네 조각은 GitLab MR 파이프라인에서 사용할 수 있다([ADR-0003](adr/0003-gitlab-ci-remote-include.md)).

- **GitLab 전용이다.** 대상 저장소의 `.gitlab-ci.yml`이 키트의 조각을 `include: remote:`로 게시된 전체 커밋 SHA에 고정해 참조한다.
  파일은 복사하지 않는다
- **GitHub 저장소용 조각은 없다.** GitHub Actions에서는 같은 도구(gitleaks, trivy, semgrep)를 직접
  호출해야 한다. 키트 저장소 자신의 적용 예는 `.github/workflows/security.yml`이다
- 설정 방법·필요 조건·끄는 법은 [`core/ci/README.md`](../core/ci/README.md)를 따른다
- Claude MR 리뷰 조각(`claude-review.yml`)은 선택이며 서버 준비가 필요하다. MR 파이프라인이 아니라 보호 브랜치
  파이프라인에서 돈다(14절)

## 6. hooks 설정

hooks는 `init`이 설치하지만, 무엇을 보호하고 무엇을 검증할지는 `harness.json`의 `hooks` 절로 정한다.
이 절은 **생략할 수 있고**, 생략하면 기본 보호 경로만 적용되고 종료 검증은 영역 설정만 쓴다.

```json
{
  "hooks": {
    "protected_paths": [
      {"pattern": "docs/api/**", "mode": "block", "reason": "API 계약"}
    ],
    "stop_verify": ["python -m pytest -q"],
    "stop_timeout_sec": 300,
    "python": "python3"
  }
}
```

| 키 | 값 | 설명 |
| --- | --- | --- |
| `protected_paths` | 객체 목록 | 지정하면 기본 목록을 **대체**한다. `pattern` 필수, `mode`는 `block` 또는 `ask` 필수, `reason`은 선택 |
| `stop_verify` | 문자열 목록 | 영역 밖 파일이 바뀌었을 때 실행할 명령. 파일을 고치지 않는 명령만 적는다 |
| `stop_timeout_sec` | 1~840 정수 | 명령별 시간 제한. 기본 300. 전체 예산도 840초다 |
| `python` | 명령 이름 또는 `py -3` | hook을 실행할 인터프리터. 기본 `python3`. 셸 메타문자·경로·임의 인자는 허용하지 않는다 |

규칙과 기본 보호 목록, 우회 경로는 [`core/hooks/README.md`](../core/hooks/README.md)에 자세히 있다.

`protected_paths`·`stop_verify`·`stop_timeout_sec`는 hook이 실행할 때마다 다시 읽으므로 고친 뒤
`init`을 다시 할 필요가 없다. **`python`만 예외다** — `.claude/settings.json`에 값이 박히므로
`init --force`로 다시 생성해야 한다.

## 7. Windows의 `hooks.python`

Windows에서 hooks가 아무 일도 안 하는 것처럼 보이면 대부분 이 문제다.

`hooks.python`의 기본값은 `python3`인데, Windows에서 `python3`는 실제 Python이 아니라
**Microsoft Store 앱 실행 별칭**인 경우가 많다. 별칭이 가리키는 앱이 설치돼 있지 않으면 Store 페이지를
열고 종료 코드 49로 끝난다. hook이 실패해도 편집은 계속되므로 **보호가 조용히 꺼진 상태**가 된다.

### 확인

```powershell
where.exe python3
python3 --version
```

- `...\AppData\Local\Microsoft\WindowsApps\python3.exe` 가 나오면 별칭이다
- `python3 --version`이 버전을 출력하지 않거나 Store가 열리면 **그대로 쓰면 안 된다**
- 별칭이어도 버전이 정상 출력되면 동작은 한다. 다만 `python`과 **다른 인터프리터**일 수 있으므로
  두 명령의 버전을 비교해 둔다

### 조치

`harness.json`에 실제로 동작하는 명령을 지정하고 `settings.json`을 다시 만든다.

```json
{ "hooks": { "python": "py" } }
```

```bash
python bin/harness.py init ../my-project --force
```

`py`(Python Launcher)가 가장 안전하다. `python`도 되지만, PATH에서 Store 별칭이 먼저 잡히지 않는지
`where.exe python`으로 확인한다.

> 별칭 자체를 끄려면 **설정 → 앱 → 고급 앱 설정 → 앱 실행 별칭**에서 `python3.exe`를 끈다.
> 다만 이건 PC마다 해야 하므로, 팀에 공유되는 `harness.json`에 `python`을 지정하는 편이 확실하다.

## 8. 설치 확인

```bash
python bin/harness.py check ../my-project
```

- 드리프트가 없으면 검사한 파일 수를 출력하고 종료 코드 0
- 템플릿과 다르거나 없는 파일, `.claude/hooks/`의 여분 파일이 있으면 목록을 출력하고 종료 코드 1
- `harness.json`의 `harness_version`이 키트 버전과 달라도 종료 코드 1

생성된 파일은 손으로 고치지 않는다. 내용을 바꾸려면 키트의 `core/templates/`를 고치고 다시 생성한다.
저장소 고유 내용은 생성 대상이 아닌 별도 문서에 둔다.

hooks가 실제로 동작하는지는 `check`로 알 수 없다. Claude Code 세션에서 lock 파일 같은 보호 경로를
편집해 보고 거부되는지 확인한다.

## 9. 끄는 법

사람이 판단해 끈다. 끈 사실과 이유는 `friction` 이슈로 남긴다([개발 계획](roadmap.md) 1장 "팀 수용").

| 범위 | 방법 |
| --- | --- |
| hooks 전체 | `.claude/settings.local.json`에 `{"disableAllHooks": true}`. 개인 설정이라 커밋하지 않는다 |
| 보호 경로 하나 | `harness.json`의 `hooks.protected_paths`를 조정한다 |
| 종료 검증 | `hooks.stop_verify`를 지우거나 더 빠른 명령으로 바꾼다. 영역의 `verify`는 필수라 영역 단위로는 끌 수 없다 |
| CI 조각 하나 | `.gitlab-ci.yml`의 해당 `include`를 제거한다. [`core/ci/README.md`](../core/ci/README.md) |

## 10. 제거

```bash
cd ../my-project
rm -rf .claude/hooks
rm .claude/settings.json harness.json
```

문서(`AGENTS.md`, `CLAUDE.md`, `docs/`)와 병합 요청 템플릿은 저장소의 내용이므로 지울지는 따로 판단한다.
CI 조각(5절)을 붙였다면 CI 정의에서 해당 `include`와 그 조각의 job 참조도 지운다.
Claude MR 리뷰를 켰다면 `.harness/claude-review/`도 지운다(14절).

`.claude/settings.local.json`은 개인 설정이라 키트가 만들지 않았다. 지우지 않는다.

## 11. 문제 해결

| 증상 | 원인과 조치 |
| --- | --- |
| `설정 파일이 없다: .../harness.json` | 루트 `init`을 먼저 실행한다. `--area`는 루트 `init` 이후에만 쓴다 |
| `tracker가 jira이면 issue_prefix가 필요하다` | `--issue-prefix`를 주거나 `--tracker github`을 쓴다 |
| `--area 에는 --verify-cmd 가 하나 이상 필요하다` | 그 영역의 검증 명령을 하나 이상 준다 |
| `--area 는 대상의 harness.json 설정을 쓰므로 ... 함께 쓸 수 없다` | 영역 생성에서 루트 인자를 뺀다 |
| `이미 존재하는 파일이 있어 중단한다` | 4절 |
| `영역 dir은 정규화된 형태여야 한다` | `harness.json`의 `areas[].dir`을 손으로 고칠 때 난다. `./backend`나 `backend/`가 아니라 `backend`로 적는다. `--area`로 줄 때는 자동으로 정규화되므로 이 오류가 나지 않는다 |
| hooks가 아무 반응이 없다 | 7절. `.claude/settings.json`이 있는지, `hooks.python`이 동작하는지 확인한다 |
| 모든 편집이 거부된다 | hook 스크립트가 없으면 Python이 종료 코드 2를 내서 전부 거부된다. `init --force`로 다시 설치한다 |
| 콘솔에 한국어가 깨진다 | 명령 출력은 UTF-8로 맞춰 두었다. 그래도 깨지면 `chcp 65001` 후 다시 실행한다 |

## 12. 다음 단계

- 판정 단계와 플랜·리뷰를 켜는 조건: [기여 규칙](contributing.md)
- hooks의 규칙·동작·알려진 우회: [`core/hooks/README.md`](../core/hooks/README.md)
- GitLab CI 조각: [`core/ci/README.md`](../core/ci/README.md)
- 설계 결정의 배경: [ADR](adr/README.md)

## 13. 첫 소비자 계약 (0.2.0)

`harness.json`의 루트 키는 `harness_version`, `project_name`, `platform`, `tracker`, `issue_prefix`,
`default_branch`, `integration_branch`, `related_docs`, `areas`, `hooks`, `judge`(선택, 3.4절), `claude_review`(선택, 14절)다. 알 수 없는 키나 타입이
틀린 값은 오류로 처리한다. `related_docs` 항목은 문자열 `label`·`path`만 가진다. `areas` 항목은
`dir`·`verify`와 선택 항목 `triggers`·`review_focus`·`docs`·`trigger_paths`·`test_paths`를 가진다.
`trigger_paths`는 `strict`·`standard` 키만 가진 객체이고 값은 패턴 목록이다(빈 목록 허용). `test_paths`는 패턴
목록이다. 영역을 새로 만들면 기본 `triggers`·`review_focus`·`trigger_paths`·`test_paths`를 설정 파일에 저장한다. 같은 영역을 `--force`로 다시 만들 때 생략한
선택 항목은 이전 값을 유지한다.
최상위 `judge`(선택)는 영역 밖 파일의 판정 규칙으로 `trigger_paths`·`test_paths`·`triggers`(사람 확인 문장)만 가진다.

템플릿의 `{{name}}`은 키트가 가진 값으로 치환한다. 이름은 소문자와 밑줄만 사용한다. 지원 이름은 `project_name`, `platform`,
`pr_noun`, `pr_long`, `ci_variables`, `tracker_name`, `issue_noun`, `issue_key`,
`issue_key_example`, `branch_key_example`, `default_branch`, `integration_branch`, `related_docs`,
`hook_python`, `review_perspectives`, `review_perspectives_ci`다. 마지막 둘은 리뷰 관점 원본
(`core/templates/review-perspectives.md`)의 절을 묶은 값이다(공통+로컬, 공통+CI). 영역 템플릿에는 `area_dir`, `area_docs`, `area_verify`, `area_triggers`,
`area_review_focus`가 추가된다. 알 수 없는 이름이나 잘못된 표기는 생성 오류다. 생성 파일 목록과 원본 경로는
`core/templates/manifest.json`이 정의하며, 이는 소비자 설정이 아닌 키트 작성자용 계약이다.
매니페스트의 `includes`는 원본 파일의 `##` 절을 골라 자리표시자 값으로 넣는다. 원본을 고치면 생성 파일이 바뀌므로
`check`가 불일치로 보고한다. 항목의 `base`는 `templates`(기본)·`hooks`·`ci`(`core/ci/`) 중 하나이고, `requires`를 주면
`harness.json`에 그 블록(현재 `claude_review`만)이 있을 때만 생성한다.

## 14. Claude MR 리뷰 (선택, GitLab)

열린 MR의 diff를 도구 없는 Claude Code CLI로 리뷰해 MR 댓글 하나로 남긴다. feelm에서 운영하던 리뷰 러너를
옮긴 것이다. 리뷰는 참고용이며 승인·병합을 대신하지 않는다. 동작과 정책은
[`core/ci/README.md`](../core/ci/README.md) "Claude MR 리뷰"에 있다. 댓글 트리거(`/claude-review` webhook)는
키트에 없다. 실제 GitLab에서의 게시는 첫 소비자 적용 때 확인한다.

### 14.1 저장소 설정

`harness.json`에 `claude_review` 블록을 넣고 `init --force`로 다시 생성한다. 블록이 있으면 `init`이 스크립트와
시스템 프롬프트를 `.harness/claude-review/`에 넣고, `check`가 그 파일의 변조와 리뷰 관점 원본의 변경을 불일치로 본다.
CI는 보호된 대상 브랜치에 커밋된 이 사본만 실행한다. 블록은 `platform`이 `gitlab`일 때만 쓸 수 있다.

```json
"claude_review": {
  "target_branch": "develop",
  "credential": "api_key",
  "rules_docs": [
    {"path": "AGENTS.md"},
    {"path": "CLAUDE.md"},
    {"path": "backend/AGENTS.md", "when_changed": ["backend/"]}
  ]
}
```

| 키 | 기본값 | 설명 |
| --- | --- | --- |
| `target_branch` | (필수) | 리뷰를 돌리는 보호 브랜치. MR의 대상 브랜치도 이 값이어야 한다 |
| `environment` | `claude-review` | 리뷰 Secret의 GitLab 환경 범위. 스크립트가 `CI_ENVIRONMENT_NAME`과 대조한다 |
| `review_name` | `claude-review` | 서버 설정 경로 `/etc/<review_name>/config.json`의 이름 |
| `credential` | `api_key` | `api_key`(`ANTHROPIC_API_KEY`) 또는 `oauth`(`CLAUDE_CODE_OAUTH_TOKEN`). 고른 하나만 읽어 CLI에 넘긴다 |
| `comment_marker` | `harness-claude-review` | 댓글의 숨은 식별자 이름. 같은 토큰 사용자의 같은 SHA 댓글이 있으면 다시 게시하지 않는다 |
| `rules_docs` | `AGENTS.md`, `CLAUDE.md` | 모델에 신뢰된 규칙으로 주는 문서. `when_changed` 접두사로 바뀐 경로가 있을 때만 넣는다 |
| `limits` | 원본 값 | `max_files`(100), `max_file_diff_bytes`(128 KiB), `max_total_diff_bytes`(512 KiB), `max_title_bytes`(1 KiB), `max_description_bytes`(16 KiB), `max_guidance_bytes`(256 KiB), `max_context_files`(24), `max_context_file_bytes`(48 KiB), `max_repository_context_bytes`(192 KiB). 낮추기만 할 수 있다 |
| `timeouts` | 원본 값 | `claude_seconds`(240, 최대 300), `auth_check_seconds`(120, 최대 240), `gitlab_seconds`(20, 최대 60) |

알 수 없는 키, 틀린 타입, 빈 `target_branch`는 `init`·`check`에서 오류(종료 코드 2)이고, 실행 시점에도
`INVALID_REVIEW_POLICY`로 멈춘다.

### 14.2 서버 준비

리뷰 전용 서버 계정과 GitLab Runner가 필요하다. 아래 파일은 키트의 `core/ci/claude-review/examples/`에 있고
`init`이 설치하지 않는다. 예시의 `claude-review`(설정 이름·계정·경로)는 서버 값으로 일관되게 바꾼다.

1. 추가 그룹 없는 전용 계정을 만들고(예: `claude-review`) 그 홈에 Claude Code CLI를 설치한다. 기존 Runner와
   계정·설정·서비스를 나눈다.
2. 서버 설정 `/etc/<review_name>/config.json`을 `config.json.example`에서 만든다. 파일은 `root:<리뷰 계정 그룹>`
   소유 0640(예: `install -o root -g claude-review -m 0640`), 상위 디렉터리는 root 소유이고 그룹·기타 사용자 쓰기
   권한이 없어야 한다. 리뷰 계정은 기본 그룹으로 이 파일을 읽고, network-guard는 root로 읽는다. 소유자가 root가
   아니거나 그룹·기타 쓰기 권한이 있거나 키가 빠지거나 남으면 토큰을 읽기 전에 실패한다. 이 파일에는 토큰·API 키
   같은 비밀값을 절대 넣지 않는다(Secret은 GitLab 변수로만 받는다).

   | 키 | 설명 |
   | --- | --- |
   | `claude_cli` | CLI 절대 경로 |
   | `claude_version` | 설치한 CLI 버전(`X.Y.Z`). sandbox 검사가 대조한다 |
   | `workdir` | MR 입력·리뷰·상태 파일을 0600으로 두는 디렉터리. runner 서비스는 `PrivateTmp`라 `/tmp/<이름>`이면 된다 |
   | `account`·`uid`·`home` | 리뷰 계정 이름, UID(0 불가), 홈 |
   | `nft_table` | network-guard가 만드는 nftables 테이블 이름 |
   | `deny_ips` | **필수 입력.** 같은 망의 운영·배포 서버 공개 IPv4 전부. 기본값이 없고 비어 있으면 가드가 실패한다. NAT 뒤에 있으면 이 서버 자신의 공개 IP도 넣는다 |
   | `dns_ips` | **필수 입력.** 서버가 쓰는 DNS IPv4(예: `resolvectl status`로 확인) |
   | `gitlab_host` | GitLab 호스트 이름. sandbox 검사의 TLS 확인 대상 |

3. `.harness/claude-review/network-guard.py`와 `sandbox-probe.py`를 보호 브랜치의 사본에서 root 소유
   `/usr/local/lib/<review_name>/`(0755, 파일 0644)로 복사한다. network-guard는 자기 파일과 설정 파일의 root 소유를 확인한다.
4. 네트워크 가드: `network-guard.py --config <설정> plan`으로 규칙을 보고, `check`로 임시 network namespace에서
   검증한 뒤(`ISOLATED_NFT_CHECK: PASS`), guard 서비스로 설치한다. 규칙은 리뷰 계정 UID에만 걸리며 지정 DNS의 53,
   공개 IPv4의 443만 허용하고 `deny_ips`, 사설망·loopback·link-local·metadata·로컬 주소와 IPv6를 거부한다.
   기존 테이블이 기준과 다르면 덮어쓰지 않고 실패한다(`GUARD_MISMATCH`).
5. systemd 유닛 3개(`claude-review-guard`·`-probe`·`-runner`)를 같은 이름이 없는지 확인한 뒤 root 소유 0644로
   `/etc/systemd/system/`에 둔다. `systemd-analyze verify`를 통과하면 `systemctl daemon-reload`한다. runner와 probe는
   같은 sandbox(CPU 1개, 메모리 2/3 GiB, swap 0, 프로세스 128개, 권한 상승 차단, 다른 홈 숨김, 시스템 읽기 전용,
   제어 소켓 차단)를 쓰고 시작 전에 root가 가드를 다시 검증한다. 같은 서버의 다른 Runner 설정 디렉터리는
   `InaccessiblePaths`에 덧붙인다.
6. probe 서비스를 한 번 실행해 `SANDBOX_PROBE: PASS`를 확인한다(비밀값 없이 계정·격리·CLI 버전·TLS만 본다).
7. 리뷰 계정으로 GitLab Runner(shell executor)를 등록한다. 태그를 붙이고 protected, 프로젝트 잠금, untagged job
   비활성화를 켠다. `/etc/<review_name>/enable-runner`를 만들어야 runner 서비스가 시작된다. 보호된 CI 설정과
   인증 검사 전에는 만들지 않는다.

### 14.3 GitLab 설정

1. 조각을 넣고, 로컬 `.gitlab-ci.yml`에 두 job을 직접 만든다. 조각에는 숨은 job(`.harness-claude-auth-check`·
   `.harness-claude-review`)과 재사용 rules(`.harness-claude-auth-check-rules`·`.harness-claude-review-rules`)만 있어서
   아래 job을 적지 않으면 리뷰 job이 생기지 않는다. 러너 태그(`<리뷰 runner 태그>`), `environment.name`
   (`claude_review.environment`와 같게), 대상 브랜치(`claude_review.target_branch`와 같게, 예: `develop`)는 변수 없이
   값으로 적는다.

   ```yaml
   include:
     - remote: https://raw.githubusercontent.com/kiddo-psh/ai-dev-harness/<full-commit-sha>/core/ci/gitlab/claude-review.yml

   harness-claude-auth-check:
     extends: .harness-claude-auth-check
     tags: [claude-review]
     environment:
       name: claude-review
       action: prepare
     rules:
       - if: '$CI_COMMIT_BRANCH != "develop"'
         when: never
       - !reference [.harness-claude-auth-check-rules, rules]

   harness-claude-review:
     extends: .harness-claude-review
     tags: [claude-review]
     environment:
       name: claude-review
       action: prepare
     rules:
       - if: '$CI_COMMIT_BRANCH != "develop"'
         when: never
       - !reference [.harness-claude-review-rules, rules]
   ```

   값을 변수로 받지 않는 이유: 리뷰를 시작하려면 파이프라인 변수(`REVIEW_MR_*`)를 넣어야 하고, 파이프라인 변수는
   `.gitlab-ci.yml`의 변수를 덮어쓴다. 태그·환경·브랜치를 변수로 두면 리뷰를 시작할 수 있는 사람이 리뷰 Secret을
   다른 runner, 다른 환경 범위나 덜 보호된 브랜치로 보낼 수 있다. 첫 규칙을 빼면 모든 보호 브랜치에서 job이 나타나므로
   반드시 둔다. 재사용 rules는 브랜치 파이프라인(`$CI_COMMIT_BRANCH`가 있음)·보호 ref·파이프라인 출처만 보며
   MR·태그 파이프라인에서는 맞지 않는다. `rules` 없이 `extends`만 하면 숨은 job의 `when: never`가 남아 돌지 않는다.
   스크립트도 실행 시점에 대상 브랜치·보호 ref·환경 이름·출처를 `harness.json`과 다시 대조한다.

2. Secret을 등록한다([Secret 규칙](secret-environment-variables.md) 7장). 모두 Protected, Masked and hidden,
   Expand variable 끔, 환경 범위는 위 `environment.name`이다.
   - `credential`이 고른 하나: `ANTHROPIC_API_KEY`(기본) 또는 `CLAUDE_CODE_OAUTH_TOKEN`. 다른 하나는 등록하지 않는다.
     팀 CI에 개인 구독(OAuth)을 쓰는 것은 정책 문제가 될 수 있어 키트 기본은 API 키다
   - `GITLAB_REVIEW_TOKEN`: MR 읽기와 댓글 작성만 하는 전용 토큰(Project Access Token. 댓글 작성에 `api` scope가 필요하다. 역할은 MR 댓글을 쓸 수 있는 최소 역할)
3. 대상 브랜치를 보호하고, 그 브랜치에 push·merge할 수 있는 사람만 리뷰 파이프라인을 만들 수 있게 한다.
   `.gitlab-ci.yml`의 리뷰 job은 보호 브랜치 변경으로만 바뀌게 한다.

### 14.4 확인

1. 보호된 대상 브랜치의 web 파이프라인에서 `harness-claude-auth-check`를 수동 실행한다. 고정된 `OK` 요청 하나만
   보내며 기대 출력은 `CLAUDE_AUTH_CHECK: PASS`다.
2. Run pipeline에서 `REVIEW_MR_IID`(MR 번호)와 `REVIEW_MR_SHA`(그 MR의 현재 40자리 HEAD SHA)를 넣고
   `harness-claude-review`를 수동 실행한다. 로그에는 `MR_COLLECTION`·`REVIEW_GENERATION`·`REVIEW_PUBLISH`의 분류 코드,
   모델명과 토큰 수만 남는다.
3. 같은 SHA로 다시 실행하면 `DUPLICATE_REVIEW_SKIPPED`, 실행 중 새 커밋을 올리면 `STALE_REVIEW_REMOVED`인지 본다.

끄려면 로컬의 두 리뷰 job과 `include`를 빼고 `harness.json`의 `claude_review`를 지운 뒤 `.harness/claude-review/`를 지운다. 서버에서는
`enable-runner`를 지우고 runner 서비스를 멈춘다. 네트워크 가드는 서비스를 멈춰도 규칙을 지우지 않는다.
