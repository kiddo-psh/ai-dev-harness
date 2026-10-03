# android-kotlin

Android(Kotlin·Jetpack Compose) 폰과 Wear OS 모듈용 프로필이다(M3-4a). 같은 Gradle 빌드의 모듈(`app`, `wear`)을
영역 하나씩으로 적용한다. 엔진 계약은 [profiles/README.md](../README.md), 적용 명령은
[install.md 3.6](../../docs/install.md)을 본다.

이 프로필은 **기본값 묶음**이다. 계층과 DI는 키트가 정하지 않는다(결정 A-3·A-4). 계층 기본값은 Android 공식 앱
아키텍처 가이드(ui·domain·data)이고, 템플릿은 DI 없는 생성자 주입이다. 새 프로젝트 아키텍처 ADR이 정해지면
M3-4b에서 설정과 템플릿을 맞춘다. 그 전에 프로젝트가 먼저 바꾸려면 아래 "템플릿 덮어쓰기"를 쓴다.

기준 버전(A-2): Kotlin 2.x, AGP 8.x, Gradle Kotlin DSL + 버전 카탈로그(`gradle/libs.versions.toml`), Compose BOM,
Navigation Compose, Wear Compose Material 3. 생성 코드는 키트 저장소에서 컴파일하지 않는다. 실제 빌드 확인은
리허설(M3-5)이 맡는다.

## 적용 (모듈마다 영역 하나)

```bash
# 폰 앱 모듈: 저장소의 android/app
python bin/harness.py init ../my-project --area android/app --profile android-kotlin \
  --var base_package=com.acme.fit

# Wear OS 모듈: 저장소의 android/wear
python bin/harness.py init ../my-project --area android/wear --profile android-kotlin \
  --var module=wear --var base_package=com.acme.fit.wear --var min_sdk=30
```

| 변수 | 기본값 | 내용 |
| --- | --- | --- |
| `base_package` | (필수) | 모듈의 기본 패키지. 스캐폴드·컨벤션 파일 경로는 `base_package_path`(점 → `/`)를 쓴다 |
| `module` | `app` | Gradle 모듈 이름(한 단계). 검증 명령 `:<module>:…`과 Konsist 범위 `scopeFromProduction("<module>")`에 쓴다 |
| `app_module` | `app` | 폰 앱 모듈 이름. 규칙 `wear-not-depend-on-app`이 다른 모듈에서 이 모듈의 패키지 import를 막는다 |
| `kotlin_src` | `src/main/java` | 모듈 기준 생산 소스 루트(Android 관례. `src/main/kotlin`을 쓰면 바꾼다) |
| `kotlin_test` | `src/test/java` | 모듈 기준 단위 테스트 소스 루트 |
| `min_sdk` | `26` | `init` 안내에만 쓴다. Wear OS 모듈은 보통 30 이상 |

`module`은 한 단계 이름만 받는다(`:feature:home` 같은 중첩 모듈은 Gradle 경로와 Konsist 모듈 이름 표기가 달라 지원하지
않는다).

## 판정 기본값 (A-10)

- `verify`: `./gradlew :<module>:ktlintCheck :<module>:lintDebug :<module>:testDebugUnitTest :<module>:assembleDebug`
- `trigger_paths.strict`(영역 기준): `**/build.gradle.kts`, `**/AndroidManifest.xml`(권한), `**/proguard-rules.pro`,
  서명 키(`*.jks`, `*.keystore`), `gradle.lockfile`
- `test_paths`: `/src/test/`, `/src/androidTest/`, `*Test.kt`, `*Tests.kt`
- `triggers`: 권한 추가, 토큰·인증 정보 저장, 백그라운드 작업, 폰↔워치 데이터 동기화, 계약(API) 변경

경로 패턴은 영역(모듈) 디렉터리 기준이다. Gradle 루트에 있는 `gradle/libs.versions.toml`, `settings.gradle.kts`,
루트 `build.gradle.kts`, `keystore.properties`는 모듈 영역 밖이라 영역 규칙에 넣지 않았다. 최상위
`harness.json`의 `judge.trigger_paths.strict`에 저장소 루트 기준으로 직접 넣는다(예: `/android/gradle/libs.versions.toml`,
`/android/settings.gradle.kts`, `/android/build.gradle.kts`). 최상위 `trigger_paths`를 지정하면 공통 기본값(lock 파일·CI
정의·DB 마이그레이션)을 대체하므로 그 항목도 함께 적는다([install.md 3.4](../../docs/install.md)).

## 스캐폴드

```bash
python bin/harness.py scaffold android/app screen WorkoutSummary --target ../my-project
python bin/harness.py scaffold android/wear wear-screen HeartRate --target ../my-project
```

| 종류 | 생성 파일(모듈 기준) | 조각 |
| --- | --- | --- |
| `screen` | `<kotlin_src>/<패키지>/ui/<name_lower>/`에 `<Name>Screen.kt`(상태·콜백만 받는 무상태 Composable + `@Preview`), `<Name>Route.kt`(`collectAsStateWithLifecycle`로 상태 수집, `viewModel { <Name>ViewModel() }`), `<Name>ViewModel.kt`(`StateFlow<UiState>`), `<Name>UiState.kt`. `<kotlin_test>/…`에 `<Name>ViewModelTest.kt`(`runTest`, `StandardTestDispatcher`, `Dispatchers.setMain`) | Navigation Compose `composable(route = "<name-kebab>") { <Name>Route() }` |
| `wear-screen` | 같은 구성. 화면은 Wear Compose Material 3 `ScreenScaffold` + `ScalingLazyColumn`, 미리보기는 `AppScaffold`로 감싼다 | Wear `SwipeDismissableNavHost` 안의 `composable(...)`과 `AppScaffold` 최상위 구조 |

내비게이션 그래프 같은 공유 파일은 고치지 않는다. 출력된 조각을 사람이 붙인다. 생성물은 팀 소유라 `check` 대상이
아니다. 생성 뒤 `./gradlew :<module>:ktlintFormat`으로 프로젝트 형식에 맞춘다.

## 컨벤션 테스트 (Konsist, A-7·A-8)

`init`이 `<kotlin_test>/<패키지>/architecture/`에 두 파일을 렌더한다. 손으로 고치지 않는다(`check`가 드리프트를 본다).

| 파일 | 종류 | 내용 |
| --- | --- | --- |
| `HarnessFixedRulesTest.kt` | 고정 | 아래 규칙 4개와 범위가 비지 않았는지(모듈 이름 오류로 인한 거짓 통과 방지) |
| `HarnessLayerArchitectureTest.kt` | 설정 | 영역 `layers`·`allow`에서 생성한 `assertArchitecture { … }` |

| 규칙 ID | 내용 |
| --- | --- |
| `no-global-scope` | 생산 소스에 `GlobalScope`가 없다 |
| `viewmodel-no-android-context` | 이름이 `*ViewModel`인 클래스가 있는 파일은 `android.content.Context`·`android.app.Activity`·`androidx.activity.ComponentActivity`·`android.view.View`를 import하지 않는다 |
| `screen-no-viewmodel-param` | 이름이 `*Screen`인 함수는 `*ViewModel` 타입 매개변수를 받지 않는다(상태 수집은 `*Route`) |
| `wear-not-depend-on-app` | `app_module`이 아닌 모듈은 `app_module`의 패키지(자기 모듈과 겹치는 패키지 제외)를 import하지 않는다. 공유 코드는 공통 모듈로 옮긴다. `app_module` 영역에서는 검사를 건너뛴다 |

모든 규칙은 `Konsist.scopeFromProduction("<module>")`(테스트 소스 제외)을 본다. 고정 규칙을 끄려면 영역 설정
`disabled_rules`에 `"규칙 ID": "이유"`를 적고 `init --area <dir> --force`로 다시 만든다(엄격 트리거).

계층 기본값(A-3, 공식 가이드):

```json
"layers": {"ui": ["..ui.."], "domain": ["..domain.."], "data": ["..data.."]},
"allow": {"ui": ["domain", "data"], "domain": [], "data": ["domain"]}
```

생성 결과는 `val ui = Layer("ui", "..ui..")` … `ui.dependsOn(domain, data)`, `domain.dependsOnNothing()` 형태다.
Konsist `Layer`는 계층마다 패키지 패턴 하나(`..`로 끝남)를 받으므로 **계층마다 패턴을 하나만** 적는다(둘 이상이면 생성된
코드가 컴파일되지 않는다). 계층 이름은 Kotlin 변수 이름으로 쓰이므로 영문자·숫자·밑줄만 쓴다. 아직 패키지가 없는
계층(예: domain을 쓰지 않는 모듈)은 Konsist가 실패로 볼 수 있으니 `layers`·`allow`에서 지운다. 스캐폴드는 `ui/`만 만들므로 새 모듈(특히 워치)은 `domain`·`data` 패키지가 생길 때까지 두 계층을 지우거나 패키지를 먼저 만든다. `layers`를 빈 객체로 두면 생성 파일이 ktlint를 통과하지 못하니 계층을 하나 이상 남긴다.

## 소비자 의존성 (P-8)

키트는 소비자의 빌드·lock 파일을 고치지 않는다. 모듈 `build.gradle.kts`에 직접 추가한다(버전은 버전 카탈로그로).

```kotlin
dependencies {
    // 컨벤션 테스트
    testImplementation("com.lemonappdev:konsist:<버전>")
    testImplementation("junit:junit:4.13.2")
    // scaffold 생성물
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:<버전>")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:<버전>")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:<버전>")
    // @Preview(폰·워치 공통): implementation("androidx.compose.ui:ui-tooling-preview:<버전>"),
    //       debugImplementation("androidx.compose.ui:ui-tooling:<버전>")
    // 폰: implementation("androidx.navigation:navigation-compose:<버전>"),
    //     implementation("androidx.compose.material3:material3:<버전>")
    // 워치: implementation("androidx.wear.compose:compose-material3:<버전>"),
    //       implementation("androidx.wear.compose:compose-navigation:<버전>")
}
```

컨벤션 테스트는 JUnit 4(`org.junit.Test`)로 생성한다. Android 단위 테스트 기본 구성과 같다.

## 형식: ktlint (A-9)

ktlint Gradle 플러그인으로 `ktlintCheck`를 만든다. 템플릿은 ktlint 기본 스타일(`ktlint_official`)에 맞춰 작성했다.

```kotlin
// 모듈 build.gradle.kts
plugins {
    id("org.jlleitschuh.gradle.ktlint") version "<버전>"
}
```

Composable 함수는 대문자로 시작하므로 저장소 루트 `.editorconfig`에 예외를 둔다.

```ini
[*.{kt,kts}]
ktlint_function_naming_ignore_when_annotated_with = Composable
```

## 정적 분석·접근성: Android Lint (A-9)

AGP 내장 Android Lint를 실패로 켠다(새 의존성 없음). `lintDebug`가 검증 명령에 들어 있다.

```kotlin
// 모듈 build.gradle.kts
android {
    lint {
        abortOnError = true
        checkDependencies = true
        error += setOf("ContentDescription", "ClickableViewAccessibility", "KeyboardInaccessibleWidget", "LabelFor")
    }
}
```

위 접근성 검사는 View·XML 기준이다. Compose의 `Image`·`Icon`은 `contentDescription` 매개변수가 필수라 컴파일러가 빠뜨림을
막지만 `null`은 허용하므로, 장식이 아닌 이미지의 `null`은 리뷰(관점: 접근성)에서 본다. detekt는 범위 밖이다.

## 의존성 잠금 (필수, A-11)

키트의 의존성 감사 조각(`trivy fs`)은 `gradle.lockfile`이 있어야 Gradle 의존성을 본다. Android 모듈은 잠금을 기본으로
켜지 않으므로 **모든 모듈에 켠다**. 조각은 바꾸지 않는다.

```kotlin
// 모듈 build.gradle.kts (또는 루트에서 subprojects { … })
dependencyLocking {
    lockAllConfigurations()
}
```

```bash
./gradlew :app:dependencies :wear:dependencies --write-locks   # 모듈마다 gradle.lockfile 생성, 커밋한다
```

의존성을 바꾸면 같은 명령으로 잠금을 갱신한다. `gradle.lockfile` 변경은 엄격 판정이다.

## 템플릿 덮어쓰기와 M3-4b

M3-4a의 템플릿은 최소 골격이다. 프로젝트 아키텍처 ADR(계층, Hilt·Koin 등 DI)이 정해지면 M3-4b에서 프로필 기본값을
맞춘다. 그 전에 프로젝트가 생성물을 바꾸려면 프로젝트 저장소에 같은 이름의 템플릿을 둔다(파일 단위, 조각 포함).

```text
.harness/templates/android-kotlin/screen/Route.kt        # 예: hiltViewModel()로 바꾼 Route
.harness/templates/android-kotlin/screen/ViewModel.kt    # 예: @HiltViewModel + @Inject constructor
.harness/templates/android-kotlin/wear-screen/snippet.kt
```

템플릿 파일 이름은 `scaffold/<종류>/`의 이름(`Screen.kt`, `Route.kt`, `ViewModel.kt`, `UiState.kt`, `ViewModelTest.kt`,
`snippet.kt`)과 같다. 컨벤션 파일은 덮어쓰지 않고 `layers`·`allow`·`disabled_rules`로 맞춘다.
