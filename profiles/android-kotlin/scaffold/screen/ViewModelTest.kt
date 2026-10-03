package {{base_package}}.feature.{{feature}}.ui.{{name_lower}}

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertFalse
import org.junit.Before
import org.junit.Test

/**
 * ViewModel 단위 테스트는 Hilt 없이 생성자로 만든다(ADR-06). Repository를 받게 되면 테스트 소스의 Fake 구현을 넘긴다.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class {{name_pascal}}ViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        // viewModelScope는 Dispatchers.Main을 쓴다. 단위 테스트에서는 테스트 디스패처로 바꾼다
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun initialStateIsNotLoading() {
        runTest {
            val viewModel = {{name_pascal}}ViewModel()

            assertFalse(viewModel.uiState.value.isLoading)
        }
    }

    @Test
    fun refreshFinishesLoading() {
        // 자리표시 테스트: 지금 ViewModel은 중단 지점 없이 로딩을 켜고 끄므로 끝 상태만 본다.
        // Repository 호출을 넣으면 Fake를 지연시켜 isLoading이 true였다가 false가 되는 전이를 단언하도록 바꾼다
        runTest {
            val viewModel = {{name_pascal}}ViewModel()

            viewModel.onRefresh()
            advanceUntilIdle()

            assertFalse(viewModel.uiState.value.isLoading)
        }
    }
}
