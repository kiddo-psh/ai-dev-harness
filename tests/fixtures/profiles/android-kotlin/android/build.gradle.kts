// 리허설 fixture(M3-5). Gradle wrapper는 커밋하지 않는다. 리허설 스크립트가 CI의 고정 버전 Gradle로 만든다(결정 H-2)
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.kotlin.compose) apply false
    alias(libs.plugins.ktlint) apply false
}
