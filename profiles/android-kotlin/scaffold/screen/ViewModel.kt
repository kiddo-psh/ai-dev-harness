package {{base_package}}.feature.{{feature}}.ui.{{name_lower}}

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * 화면 상태를 [StateFlow]로 노출한다(ADR-04 ui 계층).
 * 의존성은 Repository 인터페이스만 생성자로 받는다(규칙 viewmodel-repository-only). Retrofit·Room DAO·DataSource를
 * 직접 import하지 않는다. 여러 ViewModel이 같은 로직을 쓸 때만 domain/의 UseCase를 받는다.
 * 안드로이드 UI 타입은 참조하지 않는다(규칙 viewmodel-no-android-context).
 */
@HiltViewModel
class {{name_pascal}}ViewModel
    @Inject
    constructor() : ViewModel() {
        private val _uiState = MutableStateFlow({{name_pascal}}UiState())
        val uiState: StateFlow<{{name_pascal}}UiState> = _uiState.asStateFlow()

        fun onRefresh() {
            viewModelScope.launch {
                _uiState.update { it.copy(isLoading = true) }
                // Repository 호출 자리
                _uiState.update { it.copy(isLoading = false) }
            }
        }
    }
