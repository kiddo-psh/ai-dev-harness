// SwipeDismissableNavHost { } 안에 붙인다(Wear Compose Navigation). 앱 최상위 구조는 다음과 같다
//   AppScaffold {
//       SwipeDismissableNavHost(navController = rememberSwipeDismissableNavController(), startDestination = "…") {
//           (여기에 아래 composable 블록)
//       }
//   }
// import androidx.wear.compose.navigation.composable
// import {{base_package}}.ui.{{name_lower}}.{{name_pascal}}Route
composable(route = "{{name_kebab}}") {
    {{name_pascal}}Route()
}
