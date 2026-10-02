# core/ci

대상 저장소가 `include: remote:`로 끌어 쓰는 GitLab CI 조각(ADR-0003). 보안 검사 4종(M1-6)이 있고,
MR 본문 lint(M2-2)와 Claude MR 리뷰(M2-4)가 뒤에 들어온다.

```text
core/ci/gitlab/
  secret-detection.yml   gitleaks
  dependency-audit.yml   trivy fs (npm package-lock.json, gradle.lockfile)
  sast.yml               semgrep
  image-scan.yml         trivy image
  mr-lint.yml            MR 본문 필수 절 검사 (M2-2)
  claude-review.yml      도구 없는 Claude MR 리뷰 (M2-4, feelm 이관, 보호 브랜치 파이프라인 전용)
core/ci/claude-review/   리뷰 스크립트 원본. init이 대상 저장소 .harness/claude-review/에 복사한다
  examples/              서버 설정·systemd 유닛 예시 (init이 설치하지 않는다)
```

각 조각은 단독으로 동작하고 MR 파이프라인에서만 실행된다. **예외는 `claude-review`다.** 리뷰 토큰이 MR 소스의
CI·스크립트와 함께 실행되지 않도록 보호된 대상 브랜치의 파이프라인에서만 돈다(아래 "Claude MR 리뷰").
필요한 변수와 조건은 파일 머리 주석에 있다.

## 사용법

게시된 전체 커밋 SHA로 고정해 참조한다. 쓰는 조각만 넣는다. 릴리스 태그가 게시되면 변경되지 않는 태그도
사용할 수 있다. 현재 0.2.0은 키트 버전이며 원격 태그 게시를 뜻하지 않는다.

```yaml
include:
  - remote: https://raw.githubusercontent.com/kiddo-psh/ai-dev-harness/<full-commit-sha>/core/ci/gitlab/secret-detection.yml
  - remote: https://raw.githubusercontent.com/kiddo-psh/ai-dev-harness/<full-commit-sha>/core/ci/gitlab/dependency-audit.yml
  - remote: https://raw.githubusercontent.com/kiddo-psh/ai-dev-harness/<full-commit-sha>/core/ci/gitlab/sast.yml
  - remote: https://raw.githubusercontent.com/kiddo-psh/ai-dev-harness/<full-commit-sha>/core/ci/gitlab/image-scan.yml

variables:
  HARNESS_SCAN_IMAGE: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA   # image-scan을 쓸 때

harness-image-scan:
  needs: [build-image]   # 이미지를 올리는 로컬 job
```

GitLab Container Registry가 없는 프로젝트는 빌드한 이미지를 Docker 형식 tar 아티팩트로 넘긴다.
`build-image`는 Docker 사용 권한이 있는 runner에서 실행하는 소비자 job 예시다.

```yaml
stages: [build, test]

variables:
  HARNESS_SCAN_ARCHIVE: image.tar

build-image:
  stage: build
  script:
    - docker build -t "harness-build:$CI_COMMIT_SHA" .
    - docker save "harness-build:$CI_COMMIT_SHA" -o image.tar
  artifacts:
    access: developer
    paths: [image.tar]

harness-image-scan:
  needs:
    - job: build-image
      artifacts: true
```

`HARNESS_SCAN_IMAGE`와 `HARNESS_SCAN_ARCHIVE`는 둘 중 하나만 지정한다. tar 파일이 없거나 비어 있으면
job이 실패한다. tar 아티팩트는 크기가 클 수 있으므로 프로젝트의 아티팩트 용량 제한을 확인한다.

GitLab 17.9 이상이면 `integrity: sha256-<base64>`를 함께 적어 받은 파일이 바뀌지 않았는지 확인할 수 있다.

job 이름은 `harness-`로 시작한다. `stage`(기본 `test`), `needs`, `image` 등은 같은 이름의 job을 로컬
`.gitlab-ci.yml`에 다시 적어 덮어쓴다. 로컬에 `stages`를 정의했다면 `test`를 넣거나 `stage`를 덮어쓴다.

## 정책

| 조각 | 실패 조건 | 예외 |
| --- | --- | --- |
| `secret-detection` | MR 커밋에서 Secret 발견(뒤 커밋에서 지웠어도, merge 커밋에서 넣었어도) | `.gitleaksignore`(Fingerprint), `.gitleaks.toml`(`[extend] useDefault = true` 필수) |
| `dependency-audit` | 운영 의존성의 High·Critical이면서 고친 버전이 있는 취약점. lockfile이 없는 `package.json`·`build.gradle(.kts)`, trivy가 읽지 못한 lockfile | `.trivyignore`, `HARNESS_AUDIT_SKIP_DIRS` |
| `image-scan` | 이미지의 High·Critical이면서 고친 버전이 있는 취약점. 이미지 참조·tar 입력이 모두 없거나 둘 다 지정됨, tar 파일 누락·빈 파일 | `.trivyignore` |
| `sast` | 경고만(노란색). 이 MR이 새로 만든 발견만 보고한다. merged results에서는 대상 브랜치 현재 커밋을 기준으로 삼는다. 측정(M4) 뒤 차단으로 올린다 | `# nosemgrep: <규칙 ID>`, `.semgrepignore` |

- **도구 오류는 실패다.** DB·규칙 다운로드 실패, 설정 오류, MR 변수 없음, 얕은 clone, 기준 커밋 없음이 모두
  해당한다. 검사가 돌지 않았는데 통과로 보이지 않게 한다. semgrep도 발견만 경고로 허용한다. MR이 파일을 바꿨는데
  검사한 파일이 0개면 경고한다.
- **dev·test 의존성은 막지 않는다**(npm devDependencies, Gradle test 구성). 운영에서 돌지 않는 코드로 MR을 막으면
  검사를 끄게 된다. 측정(M4) 때 다시 본다.
- **MR이 검사 설정을 바꿀 수 없다.** 저장소의 `trivy.yaml`은 읽지 않는다. `.gitleaks.toml`이 기본 규칙을 끄면
  실패한다. `HARNESS_AUDIT_SKIP_DIRS`는 glob·`.`·`..`·절대 경로를 받지 않는다.
- **예외는 리뷰로 통제한다.** 이 MR이 예외 파일(`.gitleaksignore`, `.gitleaks.toml`, `.trivyignore`,
  `.semgrepignore`, `trivy.yaml`)이나 `HARNESS_SEMGREP_CONFIG`가 가리키는 저장소 규칙 파일을 바꿨으면
  각 job 로그 맨 앞에 경고가 나온다. 실패로 만들지는 않는다.
  예외 파일을 CODEOWNERS에 올려 보안 담당 승인을 받게 한다.

  ```text
  /.gitleaksignore  @<보안 담당>
  /.gitleaks.toml   @<보안 담당>
  /.trivyignore     @<보안 담당>
  /.semgrepignore   @<보안 담당>
  ```

- Secret이 실제로 커밋됐다면 예외로 넘기지 말고 폐기·교체한다(`docs/secret-environment-variables.md`).
  `.trivyignore`에는 CVE마다 사유와 재검토 시점을 주석으로 남긴다.
- 로그와 리포트에는 Secret 값을 남기지 않는다. gitleaks는 값을 가리고, semgrep은 규칙 ID·경로·줄 번호만 남긴다.

## 필요 조건

- Docker executor runner
- 외부 접근:
  - raw.githubusercontent.com: 조각 파일
  - Docker Hub: 도구 이미지
  - mirror.gcr.io 또는 ghcr.io: trivy DB
  - semgrep.dev: 레지스트리 규칙을 쓸 때
- 폐쇄망: 조각은 `include: project:`로 미러링하고, trivy는 `TRIVY_DB_REPOSITORY`로 DB 미러를 지정한다.
  semgrep은 `HARNESS_SEMGREP_CONFIG`에 저장소 안의 규칙 파일을 준다.
- `image-scan`: 이미지 참조 방식에는 레지스트리 접근이 필요하다. `$CI_REGISTRY` 아래 이미지는 job 토큰을
  쓴다. 다른 레지스트리는 `TRIVY_USERNAME`·`TRIVY_PASSWORD`를 보호·마스킹 변수로 준다. tar 방식에는
  빌드 job이 만든 Docker 형식 이미지 아티팩트와 이를 받는 `needs`가 필요하다.

## 알려진 한계

- 커밋 메시지와 바이너리 파일의 Secret은 보지 않는다.
- npm workspaces는 상위 `package.json`에 `"workspaces"`가 있는지만 본다. 그 목록이 이 디렉터리를 포함하는지는 보지 않는다.
- trivy DB 캐시(`.trivycache/`)는 MR 파이프라인끼리 공유한다. CI 정의를 바꿀 수 있는 MR은 캐시도 바꿀 수 있으므로
  이 조각이 막는 경계 밖이다.
- 사용자가 준 `TRIVY_USERNAME`·`TRIVY_PASSWORD`는 이미지 레지스트리와 묶이지 않는다. 그 레지스트리의 이미지에만 쓴다.
- semgrep 레지스트리 규칙(`p/default`)은 버전이 고정되지 않는다. 고정이 필요하면 저장소 안의 규칙 파일을 쓴다.
- 이미지 리포트에는 이미지의 환경 변수와 빌드 이력이 들어 있다. `artifacts:access: developer`로 Developer 이상만
  받는다(GitLab 16.11 이상). 이미지에 Secret을 굽지 않는다.

## 리포트

도구별 JSON 리포트(`gitleaks-report.json`은 값을 가린다, `trivy-dependency.json`, `trivy-image.json`,
`semgrep-report.json`은 규칙 ID·경로·줄 번호만)를 30일 동안 아티팩트로 남긴다. 측정 수집기(M4-1)가 검출 건수를 여기서 읽는다.

## 끄는 법

사람이 판단해 끈다. 끈 사실과 이유는 `friction` 이슈로 남긴다.

- 조각 전체: `include`에서 뺀다.
- 한 job: 같은 이름의 job을 로컬에 다시 적고 `rules: [{when: never}]`로 덮어쓴다.
- 오탐 하나: 위 표의 예외 방식을 쓴다.

## Claude MR 리뷰

`claude-review.yml`은 열린 MR 하나를 도구 없는 Claude Code CLI로 리뷰해 댓글 하나로 남긴다. 설치(서버 계정·네트워크
가드·systemd·runner·Secret)는 [`docs/install.md`](../docs/install.md) 14절을 따른다.

| 숨은 job (재사용 rules) | 실행 조건 | 하는 일 |
| --- | --- | --- |
| `.harness-claude-auth-check` (`.harness-claude-auth-check-rules`) | 보호된 브랜치의 push·web 파이프라인, 수동 | 고정 `OK` 요청 하나로 자격 증명 확인 |
| `.harness-claude-review` (`.harness-claude-review-rules`) | 보호된 브랜치의 web 파이프라인(수동) 또는 `CLAUDE_REVIEW_TRIGGER=comment`인 api 파이프라인 | 상태 댓글 → 수집 → 생성 → 게시, `after_script`에서 상태 갱신 |

- **조각은 숨은 job만 준다.** 소비자가 로컬 `.gitlab-ci.yml`에서 `extends`로 `harness-claude-auth-check`·
  `harness-claude-review`를 만들고 러너 태그·`environment.name`·대상 브랜치 규칙(`$CI_COMMIT_BRANCH != "<대상>"`이면
  `when: never`)을 값으로 적은 뒤 재사용 rules를 `!reference`로 잇는다(`docs/install.md` 14.3). 파이프라인 변수가 CI
  변수를 덮어쓸 수 있어 이 셋을 변수로 받지 않는다. job을 적지 않거나 rules 없이 `extends`만 하면 job은 돌지 않는다.

- **MR 파이프라인에서는 돌지 않는다.** 스크립트도 대상 브랜치(`claude_review.target_branch`), 보호 ref, 환경 이름,
  파이프라인 출처를 다시 확인하고 debug trace가 켜져 있으면 거부한다. 판정 기준은 보호 브랜치 체크아웃의
  `harness.json`이다.
- **실행하는 코드는 보호 브랜치의 `.harness/claude-review/` 사본뿐이다.** MR 브랜치는 checkout하지 않고 GitLab API로
  메타데이터와 diff만 받는다. fork MR, 대상 브랜치가 다른 MR, 입력한 SHA와 현재 HEAD가 다른 MR은 거부한다.
- **도구 없는 실행.** `--tools ""`, slash command·설정 파일·MCP·hook·세션 저장을 끄고 빈 HOME에서 한 번만 응답받는다.
  이 인자 목록은 `review_common.CLI_ARGS` 상수이며 테스트가 고정한다. 자식 프로세스에는 `credential`이 고른 자격 증명
  하나와 고정 환경만 넘기고 GitLab 토큰·다른 자격 증명·proxy는 넘기지 않는다.
- **MR 내용은 신뢰하지 않는다.** 시스템 프롬프트는 리뷰 관점 원본의 공통+CI 절(`review_perspectives_ci`)에서 렌더한
  `.harness/claude-review/system-prompt.md`다. MR 설명은 근거로 쓰지 않는다. 신뢰된 규칙은 `claude_review.rules_docs`
  allowlist만 읽고 MR 경로를 로컬 경로로 쓰지 않는다. 결과는 스키마·심각도·변경 파일·줄 번호를 검증한 뒤에만 게시한다.
- **댓글.** 숨은 식별자(`comment_marker`, 프로젝트·MR·SHA)로 같은 토큰 사용자의 기존 리뷰가 있으면 다시 게시하지 않는다.
  게시 전 두 번, 게시 후 한 번 HEAD를 확인하고 그사이 새 커밋이 오면 방금 만든 댓글만 지운다. 모델 문자열은 코드 블록에
  가둬 멘션·링크·quick action으로 해석되지 않게 한다.
- **크기 상한.** 파일 100개, 파일당 diff 128 KiB, 전체 512 KiB, GitLab이 접은 diff는 리뷰하지 않고 실패한다.
  `claude_review.limits`로 낮출 수 있다.
- **로그.** 분류 코드, 모델명과 토큰 수만 남긴다. 토큰, MR diff, 리뷰 원문은 출력하지 않는다.
- **네트워크 가드.** 리뷰 계정 UID에만 nftables 규칙을 건다(DNS 53과 공개 IPv4 443만 허용). 공개 HTTPS 전체를 허용하므로
  도메인 단위 차단은 아니다. 그래서 MR 소스를 실행하지 않고 도구도 허용하지 않는다.
- 리뷰는 참고용이며 `allow_failure: true`다. 승인·병합 판단은 사람이 한다.

## 키트 자기 적용

키트 저장소의 PR에서는 `.github/workflows/security.yml`이 `secret-detection`과 `sast` 조각을 GitHub Actions로 실행한다(M1-7).
`.github/scripts/run_fragment.py`가 조각에서 이미지·job 변수·스크립트·`allow_failure: exit_codes`를 꺼내 `docker run`으로
돌리고, GitLab MR 변수는 PR merge 커밋에서 만든다(첫 부모 = 대상, 둘째 부모 = PR head, 그 merge-base = 기준).
셸은 GitLab Docker executor처럼 bash가 있으면 `bash -eo pipefail`이다. 조각의 형식은 이 러너가 읽는 모양을 지킨다.
최상위 job 하나, 알려진 키(`stage`·`image`·`variables`·`cache`·`rules`·`interruptible`·`allow_failure`·`script`·`artifacts`),
`script:` 아래 `- |` 블록 하나, 변수 값은 큰따옴표 또는 맨 값(`$` 없음)이다. 모르는 모양은 실패한다(스크립트 일부만 돌려 통과하지 않는다).
PR이 workflow·러너·조각을 바꿨으면 job 로그에 경고가 나온다.
키트에는 lockfile과 이미지가 없어 의존성 감사·이미지 스캔은 리허설(M1-8)에서 돌린다.
`claude-review`는 자기 적용하지 않는다. 스크립트 단위 테스트(`tests/test_claude_review*.py`)만 돈다.

`ci.yml`의 `rehearsal` job은 `.github/scripts/rehearse.py`로 `init` 대상에 fixture를 만들어 조각 4종을 모두 실행한다.
검출 시나리오(지운 Secret, lodash 4.17.20 CVE-2021-23337, log4j-core 2.14.1 CVE-2021-44228, alpine 3.10 CVE-2021-36159,
SAST 발견, lockfile 누락, 이미지 입력 누락)는 종료 코드와 리포트의 기대 ID를 함께 본다. 도구 오류로 실패한 것을
기대대로 실패한 것으로 읽지 않기 위해서다. 가짜 Secret과 취약 lockfile은 실행 중에 만들고 키트에 커밋하지 않는다.
외부 레지스트리와 DB에 기대므로 필수 체크로 두지 않는다. 로컬에서는 `python .github/scripts/rehearse.py security`로 돌린다.

## 갱신

도구 버전은 태그와 digest로 고정한다(보안 도구 자체가 공급망 경로다). 버전을 올리는 것도 보안 검사
변경이라 엄격 판정이다(`docs/contributing.md`).
