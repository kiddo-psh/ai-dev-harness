# profiles

스택 종속 기능(ADR-0004). 프로필은 "기본값 묶음"이다. 아키텍처는 키트가 정하지 않고 프로젝트 설정과 템플릿 덮어쓰기로
맞춘다. core(`bin/harness.py`)는 프로필 이름을 모르고 `profile.json` 스키마만 안다. 프로필 코드는 실행하지 않는다.

프로필: `spring-java`(M3-2), `react-ts`(M3-3), `android-kotlin`(M3-4a·4b, 모듈 영역)과 `android-konsist`(M3-4b, Android
컨벤션 테스트 전용 모듈 영역). 한 Gradle 빌드에 두 프로필을 영역별로 함께 적용한다. 적용 방법은
[install.md 3.6](../docs/install.md)을 본다.

## 구조

```text
profiles/<name>/
  profile.json         정의: 검증 명령, 영역 판정 기본값, 변수, 스캐폴드 종류, 컨벤션 파일, 계층 규칙 기본값
  scaffold/<kind>/     스캐폴드 템플릿(종류별). 한 번 생성하고 팀이 소유한다
  conventions/         컨벤션 테스트·lint 설정 템플릿. 소비자 저장소에 렌더되고 `check`가 드리프트를 본다
  README.md            프로필 적용 방법, 소비자가 추가할 의존성
```

## `profile.json`

| 키 | 필수 | 내용 |
| --- | --- | --- |
| `name` | 예 | 디렉터리 이름과 같다. `[a-z0-9][a-z0-9-]*` |
| `description` | 예 | 한 줄 설명 |
| `verify` | | 영역 검증 명령 기본값. 변수(`{{base_package}}` 등)를 쓸 수 있다 |
| `trigger_paths`·`test_paths`·`triggers`·`review_focus` | | 영역 판정·AGENTS.md 기본값(형식은 `harness.json` 영역 키와 같다) |
| `vars` | | `{이름: {description, pattern?, default?}}`. 기본값이 없으면 필수. 기본값은 앞에서 선언한 변수를 쓸 수 있다. 모든 변수에 `<이름>_path`(점 → `/`)가 파생된다 |
| `scaffold` | | `{종류: {description, files: [{src, dest}], snippet?, vars?}}`. `src`는 `scaffold/<종류>/` 기준, `dest`는 영역 기준 |
| `conventions` | | `{rules, formats, files: [{src, dest, kind}]}`. `kind`는 `fixed`(고정 규칙) 또는 `configured`(계층 설정 규칙) |
| `layers`·`allow` | | 계층 규칙 기본값. `init`이 영역 설정에 굳힌다 |
| `setup_notes` | | `init` 뒤에 출력할 안내(소비자 빌드 파일에 추가할 의존성 등). 키트는 소비자 빌드·lock 파일을 고치지 않는다 |

변수 이름은 `[a-z][a-z_]*`이고 `_path`로 끝나거나 `name`으로 시작할 수 없다(엔진이 만드는 값).

## 템플릿 자리표시자

- `verify`·`setup_notes`: 변수, `<변수>_path`, `area_dir`(영역 경로). 영역 검증 명령은 저장소 루트에서 실행되므로 `cd {{area_dir}} && …`·`npm --prefix {{area_dir}} …`처럼 쓴다. `area_dir`는 변수 이름으로 쓸 수 없다
- 스캐폴드: 변수, `<변수>_path`, 이름 변형 `name`(입력 그대로)·`name_pascal`·`name_camel`·`name_kebab`·`name_snake`·`name_lower`
- 컨벤션 `fixed`: 변수와 `<변수>_path`
- 컨벤션 `configured`: 위에 더해 `formats`의 서식 이름, `layers_json`·`allow_json`(JS 설정에 그대로 쓰는 JSON). 서식 이름으로 `layers_json`·`allow_json`은 쓸 수 없다

템플릿 본문에는 자리표시자가 아닌 `{{`·`}}`를 쓸 수 없다(이스케이프 없음). JSX `style={{…}}`처럼 필요하면
`{ {`·`} }`로 띄워 쓴다. 본문·조각·기본값의 자리표시자는 프로필을 읽을 때 검사한다.

`dest`를 렌더한 결과에서 빈 구간은 접힌다(기본값이 빈 문자열인 선택 변수). 절대 경로나 `..`는 오류다.

## 계층 서식 (`conventions.formats`)

계층 규칙 생성기는 코드가 아니라 서식 데이터다. 서식마다 `layers` 순서대로 계층 하나를 렌더해 `separator`(기본 줄바꿈)로 잇는다.

| 서식 키 | 쓰는 값 | 기본 |
| --- | --- | --- |
| `layer`(필수) | `{{layer}}`, `{{patterns}}`, `{{allowed}}` | |
| `layer_empty` | `allow`에 없거나 빈 계층에 `layer` 대신 쓴다 | `layer` |
| `pattern`·`pattern_separator` | `{{pattern}}` 하나 / 이음 | `{{pattern}}` / `, ` |
| `allowed`·`allowed_separator` | `{{name}}` 하나 / 이음 | `{{name}}` / `, ` |
| `separator` | 계층 사이 | 줄바꿈 |

`allow`에 없는 의존은 금지다. 계층이 `allow`에 없으면 어떤 계층에도 의존하지 않는다. 엔진은 여집합을 계산하지 않으므로
대상 도구의 "의존 허용" API가 빠진 계층을 막지 않으면(예: Konsist `dependsOn`은 "의존해도 된다"만 뜻한다) 프로필이
서식으로 계층·`allow`를 데이터로 렌더하고 생성 코드에서 나머지 계층을 금지한다(`android-konsist` 참고).

## 고정 규칙 블록과 끄기

`conventions.rules`에 규칙 ID(`[a-z0-9][a-z0-9-]*`)와 설명을 선언하고, 템플릿에서는 언어의 주석 안에 표식을 둔다.

```text
// harness:rule no-field-injection
...규칙 코드...
// harness:end
```

영역 설정 `disabled_rules`에 `{"no-field-injection": "끈 이유"}`를 적으면 그 블록이 표식과 함께 빠진다. 이유는 비울 수 없다.
선언하지 않은 ID, 짝이 맞지 않는 표식, 블록이 없는 규칙은 오류다. 프로필 영역의 엄격 트리거에는
`layers`·`allow`·`disabled_rules` 변경 문장이 항상 들어간다. `harness.json`은 저장소 루트라 최상위 `judge.triggers`에도 문장을 넣는다.

## 템플릿 덮어쓰기

프로젝트 저장소의 `.harness/templates/<profile>/<kind>/<src>`가 있으면 프로필의 `scaffold/<kind>/<src>` 대신 쓴다(파일 단위,
조각 포함). 아키텍처 ADR에 맞춰 생성물을 바꿀 때 쓴다. 컨벤션 파일은 덮어쓰지 않고 `layers`·`allow`·`disabled_rules`로 맞춘다.
