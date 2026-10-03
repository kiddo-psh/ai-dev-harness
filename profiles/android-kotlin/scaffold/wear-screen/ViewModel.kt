package {{base_package}}.ui.{{name_lower}}

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * 화면 상태를 [StateFlow]로 노출한다. 데이터 계층 의존성(Repository 등)은 생성자 매개변수로 받는다
 * (DI 없는 생성자 주입. DI 프레임워크는 프로젝트 아키텍처 ADR이 정한다).
 * 안드로이드 UI 타입은 참조하지 않는다(규칙 viewmodel-no-android-context).
 */
class {{name_pascal}}ViewModel : ViewModel() {
    private val _uiState = MutableStateFlow({{name_pascal}}UiState())
    val uiState: StateFlow<{{name_pascal}}UiState> = _uiState.asStateFlow()

    fun onRefresh() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true) }
            // 데이터 계층 호출 자리
            _uiState.update { it.copy(isLoading = false) }
        }
    }
}
