// 규칙을 모두 끄면 assertFalse import가 남는다. 이 파일은 harness check가 관리해 손으로 못 고치므로 해당 검사만 끈다
@file:Suppress("ktlint:standard:no-unused-imports")

package {{base_package}}.architecture

import com.lemonappdev.konsist.api.Konsist
import com.lemonappdev.konsist.api.verify.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * ai-dev-harness 프로필 android-kotlin의 고정 규칙(Konsist). 손으로 고치지 않는다(harness check가 드리프트를 본다).
 * 규칙을 끄려면 harness.json 영역의 disabled_rules에 "규칙 ID": "이유"를 적고 init --area --force로 다시 만든다.
 */
class HarnessFixedRulesTest {
    private val module = "{{module}}"
    private val scope = Konsist.scopeFromProduction(module)

    @Test
    fun moduleHasProductionSources() {
        // 모듈 이름이 틀려 범위가 비면 아래 규칙이 모두 거짓 통과한다
        assertTrue("모듈 $module 의 생산 소스를 찾지 못했다", scope.files.isNotEmpty())
    }
    // harness:rule no-global-scope

    @Test
    fun noGlobalScope() {
        // 수명 없는 코루틴은 누수와 취소 누락을 만든다. viewModelScope·lifecycleScope처럼 수명 있는 범위를 쓴다
        // 주석·KDoc·문자열의 언급은 사용이 아니므로 지운 뒤 본다
        val commentsAndStrings = Regex("/\\*[\\s\\S]*?\\*/|//[^\\n]*|\"(?:\\\\.|[^\"\\\\\\n])*\"")
        val globalScope = Regex("\\bGlobalScope\\b")
        scope.files.assertFalse { file ->
            globalScope.containsMatchIn(commentsAndStrings.replace(file.text, ""))
        }
    }
    // harness:end
    // harness:rule viewmodel-no-android-context

    @Test
    fun viewModelDoesNotReferenceAndroidUi() {
        // ViewModel은 화면보다 오래 산다. Context·Activity·View를 잡으면 누수가 난다
        val forbidden =
            setOf(
                "android.content.Context",
                "android.app.Activity",
                "androidx.activity.ComponentActivity",
                "android.view.View",
            )
        scope.files.assertFalse { file ->
            file.classes().any { it.name.endsWith("ViewModel") } &&
                file.imports.any { it.name in forbidden }
        }
    }
    // harness:end
    // harness:rule screen-no-viewmodel-param

    @Test
    fun screenDoesNotTakeViewModel() {
        // *Screen은 상태와 콜백만 받는 무상태 Composable이다. ViewModel은 *Route에서 수집한다
        scope.files.assertFalse { file ->
            file.functions().any { function ->
                function.name.endsWith("Screen") &&
                    function.parameters.any { isViewModelType(it.type.name) }
            }
        }
    }

    private fun isViewModelType(name: String): Boolean = name.removeSuffix("?").endsWith("ViewModel")
    // harness:end
    // harness:rule wear-not-depend-on-app

    @Test
    fun moduleDoesNotDependOnAppModule() {
        // 폰·워치가 함께 쓰는 코드는 공통 모듈로 옮긴다. app 모듈 자신은 검사하지 않는다
        val appModule = "{{app_module}}"
        if (module == appModule) return
        val ownPackages = scope.files.mapNotNull { it.packagee?.name }.toSet()
        val appPackages =
            Konsist
                .scopeFromProduction(appModule)
                .files
                .mapNotNull { it.packagee?.name }
                .filterNot { it in ownPackages }
                .toSet()
        scope.files.assertFalse { file ->
            file.imports.any { it.name.substringBeforeLast('.') in appPackages }
        }
    }
    // harness:end
}
