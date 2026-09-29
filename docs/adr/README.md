# 키트 설계 결정(ADR)

키트의 구조와 배포 방식처럼 한 번 정하면 전체에 영향을 주는 결정을 결정 1건당 문서 1개로 남긴다.
양식은 [`0000-template.md`](./0000-template.md)를 쓴다. 채택된 ADR의 결정 내용은 수정하지 않고,
바꾸려면 새 ADR을 쓰고 이전 것을 `대체`로 표시한다.

| ADR | 결정 | 상태 |
|---|---|---|
| [ADR-0001](./0001-separate-repo-self-application.md) | 키트는 별도 공개 저장소에서 만들고, 키트 저장소 자신에게 먼저 적용한다 | 채택 (2026-09-29) |
| [ADR-0002](./0002-install-script-over-template-repo.md) | 배포는 GitHub 템플릿 저장소가 아니라 설치 스크립트로 한다 | 채택 (2026-09-29) |
| [ADR-0003](./0003-gitlab-ci-remote-include.md) | CI 조각은 GitLab CI YAML로 쓰고 `include: remote:`로 소비한다. 키트 자기 검증만 GitHub Actions를 쓴다 | 채택 (2026-09-29) |
| [ADR-0004](./0004-core-profile-split.md) | 스택 무관 기능은 `core/`, 스택 종속 기능은 `profiles/`로 나눈다 | 채택 (2026-09-29) |
