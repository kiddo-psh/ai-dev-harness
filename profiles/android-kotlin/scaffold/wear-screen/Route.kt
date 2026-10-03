package {{base_package}}.ui.{{name_lower}}

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel

/**
 * ViewModel 상태를 생명주기에 맞춰 수집해 [{{name_pascal}}Screen]에 넘긴다.
 * ViewModel은 DI 없이 생성자로 만든다. 프로젝트 ADR이 Hilt·Koin을 고르면
 * `.harness/templates/android-kotlin/wear-screen/Route.kt`로 이 템플릿을 덮어쓴다.
 */
@Composable
fun {{name_pascal}}Route(
    modifier: Modifier = Modifier,
    viewModel: {{name_pascal}}ViewModel = viewModel { {{name_pascal}}ViewModel() },
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    {{name_pascal}}Screen(
        uiState = uiState,
        onRefresh = viewModel::onRefresh,
        modifier = modifier,
    )
}
