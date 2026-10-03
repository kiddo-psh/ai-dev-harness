package {{base_package}}.feature.{{feature}}.ui.{{name_lower}}

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp

/**
 * 상태와 콜백만 받는 무상태 화면. ViewModel은 받지 않는다(규칙 screen-no-viewmodel-param).
 * 상태 수집은 [{{name_pascal}}Route]가 맡는다. 다른 feature나 :app이 조립할 공개 Composable이다(ADR-05).
 */
@Composable
fun {{name_pascal}}Screen(
    uiState: {{name_pascal}}UiState,
    onRefresh: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(text = "{{name_pascal}}")
        if (uiState.isLoading) {
            CircularProgressIndicator()
        }
        Button(onClick = onRefresh, enabled = !uiState.isLoading) {
            Text(text = "새로고침")
        }
    }
}

@Preview(showBackground = true)
@Composable
private fun {{name_pascal}}ScreenPreview() {
    {{name_pascal}}Screen(
        uiState = {{name_pascal}}UiState(),
        onRefresh = {},
    )
}
