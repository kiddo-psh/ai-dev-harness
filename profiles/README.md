# profiles

스택 종속 기능(ADR-0004). 로드맵 M3에서 채운다. 처음엔 `spring-java`와 `react-ts` 두 프로필만 만든다.

예정 구조

```text
profiles/<name>/
  profile.json         검증 명령(format · lint · test · build), 보호 경로 기본값, 엄격 단계 트리거 기본값
  scaffold/            도메인 또는 화면 생성기와 템플릿
  convention-tests/    생성물과 기존 코드가 컨벤션을 지키는지 검사하는 테스트
  README.md            적용 방법
```

`harness init --profile <name>`이 `profile.json`의 값을 대상 저장소의 `harness.json`에 병합한다.
core는 프로필 이름을 몰라야 하며, 프로필은 core의 인터페이스(`profile.json` 스키마)만 안다.
