# core/ci

대상 저장소가 `include: remote:`로 끌어 쓰는 GitLab CI 조각(ADR-0003). 로드맵 M1-6, M2-2, M2-4에서 채운다.

예정 구조

```text
core/ci/gitlab/
  secret-detection.yml   gitleaks
  dependency-audit.yml   npm audit · Gradle 의존성 취약점
  sast.yml               semgrep
  image-scan.yml         trivy
  mr-lint.yml            MR 본문 필수 절 검사 (M2-2)
core/ci/claude-review/   도구 없는 Claude MR 리뷰 (M2-4, feelm 이관)
```

각 조각은 단독으로 동작하고, MR 파이프라인에서만 실행되며, 필요한 CI 변수와 `include` 예시를 파일
머리 주석에 적는다. 태그로 고정해 참조한다.

```yaml
include:
  - remote: https://raw.githubusercontent.com/<owner>/ai-dev-harness/v0.2.0/core/ci/gitlab/secret-detection.yml
```
