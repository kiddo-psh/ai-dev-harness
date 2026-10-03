package {{base_package}}.ui.{{name_lower}}

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
        runTest {
            val viewModel = {{name_pascal}}ViewModel()

            viewModel.onRefresh()
            advanceUntilIdle()

            assertFalse(viewModel.uiState.value.isLoading)
        }
    }
}
