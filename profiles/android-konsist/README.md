# android-konsist

Android 아키텍처 테스트 **전용 모듈** 영역(예: `android/konsist-test`)용 프로필이다(M3-4b, 냠냠코치 ADR). Konsist 컨벤션
테스트 두 파일을 이 모듈 한 곳에만 렌더하고, 규칙 범위는 Gradle 루트 기준 디렉터리 변수로 나눈다(결정표 9장 Q3 (가)).
모듈 영역(app·core·feature·wear)의 검증 명령·스캐폴드는 [android-kotlin](../android-kotlin/README.md)이 맡는다. 엔진 계약은
[profiles/README.md](../README.md)를 본다.

## 적용

```bash
python bin/harness.py init ../my-project --area android/konsist-test --profile android-konsist \
  --var base_package=com.acme.fit.konsist
```

| 변수 | 기본값 | 내용 |
| --- | --- | --- |
| `base_package` | (필수) | 컨벤션 테스트 파일의 패키지 |
| `gradle_root` | `android` | 저장소 루트 기준 Gradle 빌드 루트. Konsist 프로젝트 루트도 이 디렉터리다 |
| `module` | `konsist-test` | 이 모듈의 Gradle 이름(한 단계). 영역 디렉터리 이름과 같게 둔다 |
| `kotlin_test` | `src/test/kotlin` | 모듈 기준 테스트 소스 루트(JVM 모듈) |
| `app_dir`·`core_dir`·`feature_dir`·`wear_dir` | `app`·`core`·`feature`·`wear` | Gradle 루트 기준 모듈 디렉터리. 규칙 범위를 나눈다 |

영역 검증 명령은 `<gradle_root>/gradlew -p <gradle_root> :<module>:test`(저장소 루트에서 실행)다. 생성 파일은
`<kotlin_test>/<패키지>/HarnessFixedRulesTest.kt`·`HarnessLayerArchitectureTest.kt`이고 손으로 고치지 않는다(`check`가
드리프트를 본다).

## 모듈 준비

`{gradle_root}/settings.gradle.kts`에 `include(":konsist-test")`를 더하고 모듈을 JVM 모듈로 만든다(Konsist 권장 구성).

```kotlin
// android/konsist-test/build.gradle.kts
plugins {
    kotlin("jvm")                        // 버전 카탈로그면 alias(libs.plugins.kotlin.jvm), 루트에 apply false
    id("org.jlleitschuh.gradle.ktlint")
}

tasks.test {
    // Konsist는 다른 모듈의 소스를 읽지만 Gradle은 그 소스를 입력으로 모른다.
    // 없으면 위반을 넣어도 테스트가 UP-TO-DATE로 건너뛰어진다
    outputs.upToDateWhen { false }
}

dependencies {
    testImplementation("com.lemonappdev:konsist:<버전>")
    testImplementation("junit:junit:4.13.2")
}
```

- Konsist는 `gradlew`가 있는 디렉터리를 프로젝트 루트로 찾는다. wrapper를 커밋한 Gradle 루트에서 돈다
- 컨벤션 테스트는 JUnit 4(`org.junit.Test`)로 생성한다. 리허설 fixture는 Konsist 0.17.3을 쓴다
- 범위는 `Konsist.scopeFromProduction()`(테스트 소스 제외)에서 파일의 `projectPath`(Konsist 루트 기준 경로)가
  `<dir>/`로 시작하는 것만 고른다. 중첩 모듈(`:feature:meal`)도 디렉터리 접두사 하나(`feature`)로 묶인다

## 고정 규칙 (A-8, 냠냠코치 ADR)

| 규칙 ID | 범위 | 내용 | 근거 |
| --- | --- | --- | --- |
| `no-global-scope` | app·core·feature·wear | 생산 소스에 `GlobalScope`가 없다(주석·문자열 언급 제외) | 코루틴 수명 |
| `viewmodel-no-android-context` | app·core·feature·wear | `*ViewModel` 클래스가 있는 파일은 `Context`·`Activity`·`ComponentActivity`·`View`를 import하지 않는다 | 누수 |
| `viewmodel-repository-only` | app·core·feature·wear | `*ViewModel` 클래스가 있는 파일은 `retrofit2.`·`androidx.room.` 패키지와 이름이 `*DataSource`·`*Dao`인 타입을 import하지 않는다 | ADR-04 |
| `screen-no-viewmodel-param` | app·core·feature·wear | 이름이 `*Screen`인 함수는 `*ViewModel` 타입 매개변수를 받지 않는다(상태 수집은 `*Route`) | 무상태 화면 |
| `usecase-shared-by-two-viewmodels` | feature | `*UseCase` 클래스는 `domain` 패키지에 있고, 그 이름을 쓰는 `*ViewModel` 파일이 2개 이상이다 | ADR-04 |
| `feature-no-room` | feature | `androidx.room.`을 import하지 않는다(Room은 `:core`의 Workout 테이블만) | ADR-03 |
| `wear-no-network` | wear | `retrofit2.`·`okhttp3.`·`io.ktor.`를 import하지 않는다(워치는 서버·인증을 모른다) | ADR-02 |
| `app-no-data-layer` | app | 이름이 `*Repository`·`*DataSource`·`*Dao`·`*UseCase`인 클래스·인터페이스·object를 두지 않는다(`:app`은 조립만) | ADR-05 |

범위 확인 테스트 `scopesAreNotEmpty`는 네 디렉터리마다 생산 소스가 있는지 본다. 경로 변수가 틀려 범위가 비면 규칙이 모두 거짓
통과하기 때문이다. 이 테스트는 규칙을 모두 꺼도 남는다. 프로젝트에 없는 디렉터리가 있으면(예: 워치 없음) 다른 모듈 디렉터리를
가리키게 하고 그 범위의 규칙을 `disabled_rules`로 끈다.

M3-4a의 `wear-not-depend-on-app`은 뺐다. ADR-05에서 `:wear`는 `:core`만 의존하므로 `:app` 패키지 import는 컴파일 에러가 된다.
feature 간 import 금지(ADR-05)도 Gradle 모듈 의존이 막는다.

고정 규칙을 끄려면 영역 설정 `disabled_rules`에 `"규칙 ID": "이유"`를 적고 `init --area android/konsist-test --force`로 다시
만든다(엄격 트리거). 끈 규칙 때문에 쓰지 않는 import가 남을 수 있어 생성 파일은
`@file:Suppress("ktlint:standard:no-unused-imports")`를 둔다.

## 계층 규칙 (A-3, ADR-04)

범위는 `feature_dir` 아래 생산 코드다. 기본값:

```json
"layers": {"ui": ["..ui.."], "data": ["..data.."], "domain": ["..domain.."]},
"allow": {"ui": ["data", "domain"], "data": [], "domain": ["data"]}
```

생성 파일은 두 맵을 렌더한다. `layers`는 `"ui" to Layer("ui", "..ui..")` 항목(서식 `konsist_layers`), `allow`는
`"ui" to listOf("data", "domain")`·`"data" to emptyList<String>()` 항목(서식 `konsist_allowed`)이다. 그 뒤 계층마다
`allow`가 비면 `dependsOnNothing()`, 아니면 `dependsOn(허용 계층)`과 `doesNotDependOn(나머지 계층)`(나머지가 있을 때)을
Kotlin 반복문이 부른다. Konsist 0.17.3의 `dependsOn`은 "의존해도 된다"(strict=false)만 뜻하고 빠진 계층을 막지 않기
때문이다(#59 리뷰 F2). 기본값이면 `ui`는 `data`·`domain`만, `domain`은 `data`만 의존할 수 있고 `domain`→`ui`가 실패한다.
`di` 패키지처럼 어느 계층에도 없는 패키지는 검사하지 않는다. `:core` 모델은 범위 밖이다.

- Konsist `Layer`는 계층마다 패키지 패턴 하나(`..`로 끝남)를 받으므로 계층마다 패턴을 하나만 적는다
- 계층 이름은 Kotlin 문자열로 쓰이므로 영문자·숫자·밑줄만 쓴다
- 패턴 `..ui..`는 패키지 경로 어디든 `ui` 조각이 있으면 맞으므로 `androidx.compose.ui` 같은 외부 import도 ui 계층 의존으로
  읽힌다. data·domain 파일이 Compose UI를 import하면 그 자체로 계층 위반이 된다. 프로젝트 패키지로 좁히려면
  `harness.json` 영역의 `layers`에 `com.acme.fit.feature..ui..`처럼 `<base_package>`로 시작하는 패턴을 적는다
- 계층마다 파일이 하나 이상 있어야 한다. 아직 `domain`(UseCase)이 없으면 `layers`·`allow`에서 지우고 `--force`로 다시 만든다.
  `:core`에 `..data..`처럼 계층 이름과 같은 패키지를 두면 feature에서 그 패키지 import가 계층 의존으로 읽힐 수 있으니 피한다
- feature 하나를 3계층으로 승격하는 경우(ADR-04 결과)도 이 설정으로 맞춘다

## 소유와 영역

영역(규칙 단위)과 소유(CODEOWNERS)는 별도 축이다. feature 영역 하나를 여러 소유자가 나눠 가져도 규칙은 같다. 이 모듈의
규칙·`harness.json` 영역 설정 변경은 엄격 판정이고 공통 변경이므로 프로젝트의 공통 변경 승인 규칙을 따른다. 키트는
CODEOWNERS를 만들지 않는다.
