package com.example.rehearsal.wear

import androidx.compose.runtime.Composable
import androidx.wear.compose.material3.AppScaffold
import androidx.wear.compose.material3.Text
import androidx.wear.compose.navigation.SwipeDismissableNavHost
import androidx.wear.compose.navigation.composable
import androidx.wear.compose.navigation.rememberSwipeDismissableNavController

/**
 * 워치 앱 최상위 구조. 리허설 스크립트가 `harness scaffold wear-screen` 조각을 아래 표식 자리에 붙인다.
 */
@Composable
fun WearNavHost() {
    AppScaffold {
        SwipeDismissableNavHost(
            navController = rememberSwipeDismissableNavController(),
            startDestination = "home",
        ) {
            composable(route = "home") {
                Text(text = "Home")
            }
            // rehearsal:destinations
        }
    }
}
