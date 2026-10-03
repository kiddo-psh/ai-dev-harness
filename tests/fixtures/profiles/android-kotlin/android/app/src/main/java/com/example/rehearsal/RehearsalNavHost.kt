package com.example.rehearsal

import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController

/**
 * 내비게이션 그래프. 리허설 스크립트가 `harness scaffold screen` 조각을 아래 표식 자리에 붙인다.
 */
@Composable
fun RehearsalNavHost() {
    NavHost(navController = rememberNavController(), startDestination = "home") {
        composable(route = "home") {
            Text(text = "Home")
        }
        // rehearsal:destinations
    }
}
