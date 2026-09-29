# core/hooks

AI 코딩 세션에 거는 하드 가드레일. 로드맵 M1-5(1차)와 M2-1·M2-3(판정·lint)에서 채운다.

예정 내용

- `settings.template.json` — 대상 저장소의 `.claude/settings.json` 원본. 허용 명령과 hooks 등록
- `protect-paths.py` — PreToolUse: `harness.json`의 `protected_paths`(계약 문서, 마이그레이션, CI 정의, lock 파일)에
  닿는 수정을 차단하거나 경고. 게이트 판정이 승인된 플랜 파일에 기록돼 있으면 통과
- `stop-verify.py` — Stop: 프로필의 검증 명령을 실행하고 실패하면 세션에 알림
- `judge.py` — diff에서 검증만·기본·게이트를 산출(M2-1). CLI `harness judge`와 같은 코드

원칙: 기본 경로는 조용히 돈다. 끄는 방법을 항상 문서화한다(`docs/install.md`).
