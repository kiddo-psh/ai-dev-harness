import org.gradle.api.tasks.testing.logging.TestExceptionFormat
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

// 아키텍처 테스트 전용 JVM 모듈(냠냠코치 9장 Q3 (가)). 생산 코드는 없고 android-konsist 프로필의 컨벤션 테스트만 둔다
plugins {
    alias(libs.plugins.kotlin.jvm)
    alias(libs.plugins.ktlint)
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

ktlint {
    version.set(libs.versions.ktlint.cli.get())
}

tasks.test {
    // Konsist는 다른 모듈의 소스를 읽지만 Gradle 입력이 아니다. 항상 다시 실행해야 위반을 넣었을 때 건너뛰지 않는다
    outputs.upToDateWhen { false }
    testLogging {
        events("failed")
        exceptionFormat = TestExceptionFormat.FULL
    }
}

dependencies {
    testImplementation(libs.konsist)
    testImplementation(libs.junit)
}
