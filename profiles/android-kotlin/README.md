# android-kotlin

Android(Kotlin·Jetpack Compose·Hilt) 폰·Wear OS **모듈 영역**용 프로필이다(M3-4a 기본값, M3-4b 냠냠코치 ADR 반영). 영역의
검증 명령·판정 기본값·스캐폴드를 정한다. **컨벤션 테스트(Konsist)는 이 프로필에 없다.** 아키텍처 테스트 전용 모듈 영역에
[android-konsist](../android-konsist/README.md)를 함께 적용한다. 엔진 계약은 [profiles/README.md](../README.md), 적용 명령은
[install.md 3.6](../../docs/install.md)을 본다.

엔진은 프로필 영역마다 컨벤션 파일을 렌더하고 조건부 렌더가 없다. Konsist 테스트를 한 모듈에만 두기 위해 프로필을 둘로
나눴다(결정표 9장 Q3 (가)).

기준 버전(A-2): Kotlin 2.x, AGP 8.x, Gradle Kotlin DSL + 버전 카탈로그(`gradle/libs.versions.toml`), Compose BOM,
Navigation Compose, Wear Compose Material 3, Hilt(KSP). 리허설 fixture가 실제로 빌드하는 고정 버전은
[`tests/fixtures/profiles/android-kotlin/android/gradle/libs.versions.toml`](../../tests/fixtures/profiles/android-kotlin/android/gradle/libs.versions.toml)에
있다(AGP 8.13.2, Kotlin 2.2.21, KSP 2.2.21-2.0.5, Hilt 2.57.2, androidx.hilt 1.3.0). Hilt 2.59부터 Hilt Gradle 플러그인이
AGP 9를 요구하므로 AGP 8을 쓰는 동안 Hilt는 2.57.x에 둔다. KSP 버전은 Kotlin 버전에 맞춘다(`<kotlin>-<ksp>`).

## 아키텍처 기준(냠냠코치 ADR)

| ADR | 결정 | 이 프로필에서 |
| --- | --- | --- |
| 02 | 워치는 Companion, 서버·인증 없음 | `wear-screen` ViewModel 주석, 규칙 `wear-no-network`(android-konsist) |
| 03 | 폰 오프라인은 운동만, Room은 `:core`의 Workout 테이블만 | `repository` 구현 주석, 규칙 `feature-no-room` |
| 04 | ui·data 2계층 + 조건부 UseCase(ViewModel 2곳 이상 공유 시 `domain/`) | `screen`·`repository`·`usecase` 패키지, 트리거 문장, 규칙 `viewmodel-repository-only`·`usecase-shared-by-two-viewmodels`, 계층 규칙 |
| 05 | `:app :wear :core :feature:{member,meal,workout,coaching,growth}`, feature→core만, 이동은 `:app` | 영역 4개, 스캐폴드 경로 `feature/<feature>/`, 조각을 `:app` 그래프에 붙임, 규칙 `app-no-data-layer` |
| 06 | Hilt, `@HiltViewModel`, feature가 `@Binds`, ViewModel 단위 테스트는 Hilt 없이 | 템플릿 전체 |

## 적용 (영역 5개)

영역은 소유자가 아니라 **규칙이 다른 단위**다(9장 Q3). feature 5개는 상위 디렉터리 `android/feature` 하나로 묶는다. 소유는
CODEOWNERS로 따로 나눈다(별도 축, 이 키트는 CODEOWNERS를 만들지 않는다).

```bash
T=../my-project
python bin/harness.py init $T --area android/app --profile android-kotlin --var base_package=com.acme.fit
python bin/harness.py init $T --area android/core --profile android-kotlin --var base_package=com.acme.fit.core \
  --var module=core
python bin/harness.py init $T --area android/feature --profile android-kotlin --var base_package=com.acme.fit \
  --var module=feature \
  --var gradle_tasks=":feature:member:check :feature:meal:check :feature:workout:check :feature:coaching:check :feature:growth:check"
python bin/harness.py init $T --area android/wear --profile android-kotlin --var base_package=com.acme.fit.wear \
  --var module=wear --var min_sdk=30
# 컨벤션 테스트(Konsist) 전용 모듈
python bin/harness.py init $T --area android/konsist-test --profile android-konsist \
  --var base_package=com.acme.fit.konsist
```

| 변수 | 기본값 | 내용 |
| --- | --- | --- |
| `base_package` | (필수) | 앱의 기본 패키지. feature 영역 스캐폴드는 `<base_package>.feature.<feature>` 아래, wear 영역은 워치 패키지를 준다 |
| `gradle_root` | `android` | 저장소 루트 기준 Gradle 빌드 루트(`gradlew`가 있는 곳). 저장소 루트면 `.` |
| `module` | `app` | Gradle 모듈 이름(한 단계). `gradle_tasks` 기본값과 안내에 쓴다 |
| `gradle_tasks` | `:<module>:check` | 영역 검증 명령의 Gradle 태스크(공백 구분). feature 영역은 feature 모듈을 모두 적는다 |
| `kotlin_src` | `src/main/java` | 모듈 기준 생산 소스 루트(`src/main/kotlin`이면 바꾼다) |
| `kotlin_test` | `src/test/java` | 모듈 기준 단위 테스트 소스 루트 |
| `min_sdk` | `26` | `init` 안내에만 쓴다. Wear OS 모듈은 보통 30 이상 |

## 판정 기본값 (A-10)

- `verify`: `<gradle_root>/gradlew -p <gradle_root> <gradle_tasks>`. 기본 `:<module>:check`는 ktlint 플러그인의
  `ktlintCheck`, Android Lint, 단위 테스트(`test<Variant>UnitTest`)를 함께 돈다. 영역 검증 명령은 **저장소 루트에서**
  실행되므로(`stop-verify`) Gradle 빌드 루트의 wrapper를 경로로 부르고 `-p`로 프로젝트 디렉터리를 준다. feature 영역은
  변경한 모듈과 상관없이 5개 모듈을 모두 검증한다(변경 모듈만 검증은 hooks 변경이라 후속). 이미 만든 영역을 `--force`로 다시
  만들면 `verify`는 이전 값을 유지하므로, 변수를 바꾼 뒤에는 영역의 `verify`를 직접 고치거나 영역 항목을 지우고 다시 만든다
- `trigger_paths.strict`(영역 기준): `**/build.gradle.kts`, `**/AndroidManifest.xml`(권한), `**/proguard-rules.pro`,
  서명 키(`*.jks`, `*.keystore`), `gradle.lockfile`
- `test_paths`: `/src/test/`, `/src/androidTest/`, `*Test.kt`, `*Tests.kt`
- `triggers`: 권한 추가, 토큰·인증 정보 저장, 백그라운드 작업, 폰↔워치 데이터 동기화, 계약(API) 변경.
  ViewModel→Repository만 의존·UseCase 2곳 공유(ADR-04)는 `android-konsist` 고정 규칙이 빌드에서 막으므로 사람 확인 트리거로
  두지 않는다

영역별로 더 좁은 문장은 영역 설정 `triggers`에 직접 더한다. 예: `android/core`에 "Room 테이블 추가(Workout 외 금지, ADR-03)",
`android/wear`에 "Data Layer(DataClient·MessageClient) 경로·형식 변경(ADR-02)", `android/app`에 "내비게이션 그래프의 경로
변경". 경로 패턴은 영역 디렉터리 기준이다. Gradle 루트에 있는 `gradle/libs.versions.toml`, `settings.gradle.kts`, 루트
`build.gradle.kts`, `keystore.properties`는 영역 밖이므로 최상위 `harness.json`의 `judge.trigger_paths.strict`에 저장소 루트
기준으로 직접 넣는다(9장 Q1 (a), 예: `/android/gradle/libs.versions.toml`). 최상위 `trigger_paths`를 지정하면 공통 기본값(lock
파일·CI 정의·DB 마이그레이션)을 대체하므로 그 항목도 함께 적는다([install.md 3.4](../../docs/install.md)).

## 스캐폴드

```bash
python bin/harness.py scaffold android/feature screen MealSummary --var feature=meal --target ../my-project
python bin/harness.py scaffold android/feature repository MealLog --var feature=meal --target ../my-project
python bin/harness.py scaffold android/feature usecase WorkoutVolume --var feature=workout --target ../my-project
python bin/harness.py scaffold android/wear wear-screen HeartRate --target ../my-project
```

`screen`·`repository`·`usecase`는 feature 영역용이고 종류 변수 `feature`(모듈 디렉터리 이름)가 필수다. 파일은
`android/feature/<feature>/<kotlin_src>/<패키지>/feature/<feature>/…`에 생긴다.

| 종류 | 생성 파일 | 조각 |
| --- | --- | --- |
| `screen` | `ui/<name_lower>/`에 `<Name>Screen.kt`(상태·콜백만 받는 무상태 Composable + `@Preview`), `<Name>Route.kt`(`hiltViewModel()`, `collectAsStateWithLifecycle`), `<Name>ViewModel.kt`(`@HiltViewModel` + `@Inject constructor`, `StateFlow<UiState>`), `<Name>UiState.kt`. 테스트 소스에 `<Name>ViewModelTest.kt`(Hilt 없이 생성자로 만든다, `runTest`·`Dispatchers.setMain`) | `:app` 내비게이션 그래프의 `composable(route = "<name-kebab>") { <Name>Route() }`와 import. `:app`이 그 feature 모듈에 의존해야 한다 |
| `repository` | `data/<Name>Repository.kt`(인터페이스), `data/Default<Name>Repository.kt`(`@Inject constructor`), `di/<Name>RepositoryModule.kt`(`@Module @InstallIn(SingletonComponent::class)`, `@Binds`), 테스트 소스에 `data/Fake<Name>Repository.kt`(ViewModel 테스트에 생성자로 넘기는 대역) | 없음 |
| `usecase` | `domain/<Name>UseCase.kt`(`@Inject constructor`, `operator fun invoke`). **사용하는 ViewModel이 둘이 되기 전에는 Konsist 규칙 `usecase-shared-by-two-viewmodels`가 실패한다** | 없음 |
| `wear-screen` | wear 영역의 `ui/<name_lower>/`에 `screen`과 같은 구성. 화면은 Wear Compose Material 3 `ScreenScaffold` + `ScalingLazyColumn`, ViewModel은 Hilt | Wear `SwipeDismissableNavHost` 안의 `composable(...)`과 `AppScaffold` 최상위 구조 |

`hiltViewModel()`은 `androidx.hilt:hilt-lifecycle-viewmodel-compose`의 `androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel`을
쓴다. `androidx.hilt.navigation.compose` 판은 폰 Navigation Compose를 끌어오므로 워치에 맞지 않는다. 내비게이션 그래프 같은
공유 파일은 고치지 않는다. 출력된 조각을 사람이 붙인다. 생성물은 팀 소유라 `check` 대상이 아니다. 생성 뒤
`./gradlew :<module>:ktlintFormat`으로 프로젝트 형식에 맞춘다(`@Inject constructor`를 ktlint_official 형식으로 이미 나눠 두었다).

## 소비자 의존성 (P-8)

키트는 소비자의 빌드·lock 파일을 고치지 않는다. 모듈 `build.gradle.kts`에 직접 추가한다(버전은 버전 카탈로그로).

```kotlin
plugins {
    id("com.google.devtools.ksp")          // 루트에 version, apply false
    id("com.google.dagger.hilt.android")
    id("org.jlleitschuh.gradle.ktlint")
}

dependencies {
    implementation("com.google.dagger:hilt-android:<버전>")
    ksp("com.google.dagger:hilt-android-compiler:<버전>")
    implementation("androidx.hilt:hilt-lifecycle-viewmodel-compose:<버전>")   // hiltViewModel()
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:<버전>")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:<버전>")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:<버전>")
    testImplementation("junit:junit:4.13.2")
    // @Preview: implementation("androidx.compose.ui:ui-tooling-preview:<버전>"), debugImplementation("androidx.compose.ui:ui-tooling:<버전>")
    // 폰: implementation("androidx.compose.material3:material3:<버전>"), :app은 navigation-compose
    // 워치: implementation("androidx.wear.compose:compose-material3:<버전>"), implementation("androidx.wear.compose:compose-navigation:<버전>")
}
```

`:app`과 `:wear`는 각각 `@HiltAndroidApp` Application과 `@AndroidEntryPoint` Activity를 둔다(ADR-06). Hilt Gradle 플러그인은
`hilt-android` 의존성과 함께 적용한다. Hilt 모듈을 제공하지 않는 모듈(리허설 fixture의 `:core`처럼 모델만 둔 경우)에는
플러그인을 적용하지 않아도 된다. 냠냠코치의 `:core`는 네트워크·Room·Data Layer 모듈을 제공하므로(ADR-06) 적용한다.

## 형식: ktlint (A-9)

ktlint Gradle 플러그인으로 `ktlintCheck`를 만든다(기본 `check`가 함께 돈다). 템플릿은 ktlint 기본 스타일(`ktlint_official`)에
맞춰 작성했다. Composable 함수는 대문자로 시작하므로 저장소 루트 `.editorconfig`에 예외를 둔다.

```ini
[*.{kt,kts}]
ktlint_function_naming_ignore_when_annotated_with = Composable
```

버전 카탈로그에서 플러그인과 CLI 버전 키를 `ktlint`·`ktlint-gradle`처럼 두면 접근자가 겹친다(`ktlint-gradle`·`ktlint-cli`로
둔다). `hilt`와 `hilt-…`도 같은 이유로 androidx.hilt 버전 키는 `androidx-hilt`처럼 다른 접두사를 쓴다.

## 정적 분석·접근성: Android Lint (A-9)

AGP 내장 Android Lint를 실패로 켠다(새 의존성 없음). 기본 검증 명령의 `check`가 Lint를 함께 돈다.

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
./gradlew :app:dependencies :core:dependencies :wear:dependencies --write-locks   # feature·konsist-test 모듈도 같이
```

의존성을 바꾸면 같은 명령으로 잠금을 갱신한다. `gradle.lockfile` 변경은 엄격 판정이다.

## 템플릿 덮어쓰기

ADR이 바뀌거나 프로젝트가 생성물을 더 바꾸려면 프로젝트 저장소에 같은 이름의 템플릿을 둔다(파일 단위, 조각 포함).

```text
.harness/templates/android-kotlin/screen/ViewModel.kt
.harness/templates/android-kotlin/repository/RepositoryModule.kt
.harness/templates/android-kotlin/wear-screen/snippet.kt
```

템플릿 파일 이름은 `scaffold/<종류>/`의 이름과 같다(`screen`·`wear-screen`: `Screen.kt`, `Route.kt`, `ViewModel.kt`,
`UiState.kt`, `ViewModelTest.kt`, `snippet.kt` / `repository`: `Repository.kt`, `DefaultRepository.kt`, `RepositoryModule.kt`,
`FakeRepository.kt` / `usecase`: `UseCase.kt`). 컨벤션 규칙은 [android-konsist](../android-konsist/README.md)의
`layers`·`allow`·`disabled_rules`로 맞춘다.
