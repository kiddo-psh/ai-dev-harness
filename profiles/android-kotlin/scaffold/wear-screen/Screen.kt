package {{base_package}}.ui.{{name_lower}}

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Devices
import androidx.compose.ui.tooling.preview.Preview
import androidx.wear.compose.foundation.lazy.ScalingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberScalingLazyListState
import androidx.wear.compose.material3.AppScaffold
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.ListHeader
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.Text

/**
 * 상태와 콜백만 받는 무상태 Wear OS 화면(Wear Compose Material 3). ViewModel은 받지 않는다.
 * 앱 최상위의 AppScaffold 안에서 쓰고, 화면마다 ScreenScaffold로 스크롤 상태를 연결한다.
 */
@Composable
fun {{name_pascal}}Screen(
    uiState: {{name_pascal}}UiState,
    onRefresh: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val listState = rememberScalingLazyListState()
    ScreenScaffold(scrollState = listState, modifier = modifier) { contentPadding ->
        ScalingLazyColumn(
            state = listState,
            contentPadding = contentPadding,
        ) {
            item {
                ListHeader {
                    Text(text = "{{name_pascal}}")
                }
            }
            item {
                Button(onClick = onRefresh, enabled = !uiState.isLoading) {
                    Text(text = "새로고침")
                }
            }
        }
    }
}

@Preview(device = Devices.WEAR_OS_SMALL_ROUND, showSystemUi = true)
@Composable
private fun {{name_pascal}}ScreenPreview() {
    AppScaffold {
        {{name_pascal}}Screen(
            uiState = {{name_pascal}}UiState(),
            onRefresh = {},
        )
    }
}
