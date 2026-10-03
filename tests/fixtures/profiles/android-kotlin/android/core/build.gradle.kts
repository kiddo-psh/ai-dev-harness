import org.gradle.api.tasks.testing.logging.TestExceptionFormat
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.ktlint)
}

android {
    namespace = "com.example.rehearsal.core"
    compileSdk = 36

    defaultConfig {
        minSdk = 26
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    lint {
        abortOnError = true
        textReport = true
        textOutput = file("stdout")
    }

    testOptions {
        unitTests.all {
            it.testLogging {
                events("failed")
                exceptionFormat = TestExceptionFormat.FULL
            }
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

ktlint {
    version.set(libs.versions.ktlint.cli.get())
}

dependencies {
    // ADR-05: :core가 네트워크(Retrofit)와 Room(ADR-03: Workout 테이블만)을 가진다. fixture는 의존만 노출한다.
    // feature가 이 API를 직접 쓰는 것은 컨벤션 테스트(viewmodel-repository-only·feature-no-room)가 막는다
    api(libs.retrofit)
    api(libs.androidx.room.runtime)
    testImplementation(libs.junit)
}
