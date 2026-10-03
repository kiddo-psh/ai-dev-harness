package {{base_package}}.feature.{{feature}}.ui.{{name_lower}}

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle

/**
 * ViewModel 상태를 생명주기에 맞춰 수집해 [{{name_pascal}}Screen]에 넘긴다.
 * ViewModel은 Hilt가 만든다(hiltViewModel, ADR-06). :app의 내비게이션 그래프가 이 Route를 등록한다(ADR-05).
 */
@Composable
fun {{name_pascal}}Route(
    modifier: Modifier = Modifier,
    viewModel: {{name_pascal}}ViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    {{name_pascal}}Screen(
        uiState = uiState,
        onRefresh = viewModel::onRefresh,
        modifier = modifier,
    )
}
