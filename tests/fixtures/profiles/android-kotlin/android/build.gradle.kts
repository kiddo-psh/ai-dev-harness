// 리허설 fixture(M3-5·#59). Gradle wrapper는 커밋하지 않는다. 리허설 스크립트가 CI의 고정 버전 Gradle로 만든다(결정 H-2)
// 모듈 구성은 냠냠코치 ADR-05를 줄인 것이다: :app :wear :core :feature:{meal,workout} + 아키텍처 테스트 :konsist-test
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.android.library) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.kotlin.jvm) apply false
    alias(libs.plugins.kotlin.compose) apply false
    alias(libs.plugins.ksp) apply false
    alias(libs.plugins.hilt) apply false
    alias(libs.plugins.ktlint) apply false
}
