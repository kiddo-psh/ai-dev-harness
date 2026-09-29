# 키트 문서

이 디렉터리는 두 종류의 문서를 담는다.

**키트 자체 문서** (손으로 관리)

- [개발 계획과 마일스톤](./roadmap.md)
- [기여 규칙](./contributing.md) — 브랜치·커밋·PR, 플랜·리뷰를 켜는 조건
- [설계 결정(ADR)](./adr/README.md)
- [feelm에서 이관한 항목 대장](./migration-ledger.md)

**자기 적용으로 생성된 문서** (`core/templates/`를 고친 뒤 `python bin/harness.py init --self`)

- [AI 병렬 작업 및 충돌 방지 규칙](./ai-collaboration.md)
- [Secret 및 환경변수 관리 규칙](./secret-environment-variables.md)
- [플랜 템플릿](./templates/plan.md) · [리뷰 템플릿](./templates/review.md)
- [ADR 템플릿](./adr/0000-template.md)

생성 대상 목록은 `core/templates/manifest.json`의 `self: true` 항목이다. CI가 드리프트를 검사하므로
생성된 문서를 직접 고치면 실패한다.
