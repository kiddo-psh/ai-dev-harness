// :app의 내비게이션 그래프 NavHost { } 안에 붙인다(Navigation Compose, ADR-05: 화면 간 이동은 :app이 맡는다).
// :app의 build.gradle.kts에 implementation(project(":feature:{{feature}}"))가 있어야 한다. 경로 상수를 쓰면 문자열을 그 상수로 바꾼다
// import androidx.navigation.compose.composable
// import {{base_package}}.feature.{{feature}}.ui.{{name_lower}}.{{name_pascal}}Route
composable(route = "{{name_kebab}}") {
    {{name_pascal}}Route()
}
