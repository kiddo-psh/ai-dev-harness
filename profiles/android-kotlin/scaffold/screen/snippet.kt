// 내비게이션 그래프의 NavHost { } 안에 붙인다(Navigation Compose). 경로 상수를 쓰면 문자열을 그 상수로 바꾼다
// import androidx.navigation.compose.composable
// import {{base_package}}.ui.{{name_lower}}.{{name_pascal}}Route
composable(route = "{{name_kebab}}") {
    {{name_pascal}}Route()
}
