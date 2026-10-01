# ADR-0003: CI 조각은 GitLab CI YAML로 쓰고 `include: remote:`로 소비한다

| 항목 | 값 |
|---|---|
| 상태 | 채택 |
| 결정일 | 2026-09-29 |
| 결정자 | 박시현 |
| 관련 | roadmap M1-6, M2-2, M2-4 |

## 맥락

다음 프로젝트는 SSAFY GitLab에서 돌고, 키트는 GitHub에 공개된다. 보안 검사·MR 본문 lint·Claude
리뷰 같은 CI 조각을 대상 저장소마다 복사하면 갱신이 흩어진다. GitLab CI는 공개 URL의 YAML을
`include: remote:`로 끌어올 수 있다.

## 결정

CI 조각은 `core/ci/gitlab/<name>.yml`에 단독으로 동작하는 GitLab CI YAML로 쓴다. 대상 저장소는
GitHub raw 주소를 태그로 고정해 `include: remote:`로 참조한다. 키트 자신의 검증(테스트, 드리프트,
리허설)과 자기 적용 보안 검사는 GitHub Actions에서 같은 도구를 직접 호출한다. GitHub Actions용
재사용 workflow는 만들지 않는다.

## 고려한 대안

| 대안 | 장점 | 단점 |
|---|---|---|
| A (선택) GitLab YAML + remote include | 복사 없이 버전 고정, 다음 프로젝트에 바로 적용 | GitHub 소비자는 직접 옮겨 써야 함 |
| B GitLab·GitHub 양쪽 CI 정의 유지 | 두 플랫폼 지원 | 같은 검사를 두 번 유지, 첫 적용 전 과잉 일반화 |
| C 셸 스크립트로 검사 로직을 두고 CI는 호출만 | 플랫폼 무관 | GitLab의 rules·artifacts·MR 변수 활용이 어려움 |

## 결과

- **얻는 것**: 한 곳에서 갱신되는 CI 조각, 태그로 고정된 재현성
- **감수하는 것**: GitHub 소비자 지원은 두 번째 적용 이후로 미룸
- **후속 작업**: 조각별 `include` 예시와 필요한 CI 변수 목록을 `core/ci/README.md`에 기록
- **자기 적용 방식(M1-7, #16)**: "같은 도구를 직접 호출"은 조각의 이미지·스크립트를 `.github/scripts/run_fragment.py`로
  꺼내 실행하는 방식으로 구현했다. 같은 검사를 두 벌 두지 않으려는 것이다. 대신 조각 형식이 러너가 읽는 모양으로 묶인다
