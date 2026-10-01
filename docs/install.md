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

영역 `AGENTS.md`는 3절에서 따로 생성한다. CI 조각은 아직 제공하지 않는다(5절).

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
  `<영역>/AGENTS.md` 파일은 `--force` 없이 덮어쓰지 않는다

결과로 `<영역>/AGENTS.md`가 생기고 `harness.json`의 `areas`에 설정이 기록된다.

### 3.3 첫 커밋

```bash
cd ../my-project
git add .
git commit -m "chore: ai-dev-harness 적용"
```

`.claude/settings.json`과 `.claude/hooks/`는 **커밋한다**. 팀 전체가 같은 가드레일을 쓰기 위해서다.
개인 설정은 `.claude/settings.local.json`에 두고 이 파일은 커밋하지 않는다.

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
   - 기존 내용을 살려야 하면 → 그 파일을 다른 이름으로 옮겨 두고 `init` 후 내용을 손으로 합친다
3. `--force`로 실행한다

```bash
python bin/harness.py init ../my-project --force --platform github --tracker github
```

4. `git diff`로 무엇이 바뀌었는지 확인한 뒤 커밋한다

### 주의할 점

- **`--force`는 생성 대상 파일만 덮어쓴다.** `harness.json`도 다시 쓰지만 기존 파일을 읽어서 쓰므로
  `hooks`, `areas` 같은 설정은 보존된다. 바뀌는 것은 `harness_version`이 키트 버전으로 맞춰지는 것과
  들여쓰기·키 순서뿐이다
- **`harness.json`이 이미 있으면 `--platform`·`--tracker` 같은 인자는 조용히 무시된다.** 파일의 값이
  이긴다. 값을 바꾸려면 `harness.json`을 직접 고치고 `init --force`로 다시 생성한다
- **부분 적용은 지원하지 않는다.** 일부 파일만 생성하는 인자는 없다. 필요 없는 파일은 생성 후 지우면
  되지만, 그러면 `check`가 "없음"으로 보고한다(8절)

## 5. CI 조각

> **아직 쓸 수 없다.** 보안 검사 CI 조각은 로드맵 M1-6에서 만들고 있고, 현재 `core/ci/`에는 예정 구조만 있다.
> 이 절은 M1-6이 병합되면 설정 방법으로 채운다.

예정된 방식은 다음과 같다([ADR-0003](adr/0003-gitlab-ci-remote-include.md)).

- **GitLab 전용이다.** 대상 저장소의 `.gitlab-ci.yml`이 키트의 조각을 `include: remote:`로 태그 고정해 참조한다.
  파일은 복사하지 않는다
- **GitHub 저장소용 조각은 계획에 없다.** GitHub Actions에서는 같은 도구(gitleaks, trivy, semgrep)를 직접
  호출해야 한다. 키트 저장소 자신의 적용 예는 M1-7에서 만든다
- 설정 방법·필요 조건·끄는 법은 조각과 함께 [`core/ci/README.md`](../core/ci/README.md)에 들어간다

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
| `python` | 명령 이름 | hook을 실행할 인터프리터. 기본 `python3`. 따옴표·역슬래시·제어 문자를 쓸 수 없다 |

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
- 템플릿과 다르거나 없는 파일이 있으면 목록을 출력하고 종료 코드 1
- `harness.json`의 `harness_version`이 키트 버전과 다르면 주의 문구가 먼저 나온다

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
| CI 조각 하나 | 아직 제공하지 않는다(5절). 제공되면 [`core/ci/README.md`](../core/ci/README.md)에 끄는 법을 둔다 |

## 10. 제거

```bash
cd ../my-project
rm -rf .claude/hooks
rm .claude/settings.json harness.json
```

문서(`AGENTS.md`, `CLAUDE.md`, `docs/`)와 병합 요청 템플릿은 저장소의 내용이므로 지울지는 따로 판단한다.
CI 조각(5절, 제공 예정)을 붙였다면 CI 정의에서 해당 `include`와 그 조각의 job 참조도 지운다.

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
- CI 조각(M1-6 진행 중, GitLab 전용 예정): [`core/ci/README.md`](../core/ci/README.md)
- 설계 결정의 배경: [ADR](adr/README.md)
