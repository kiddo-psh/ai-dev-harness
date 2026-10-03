// 규칙을 끄면 쓰지 않는 import가 남는다. 이 파일은 harness check가 관리해 손으로 못 고치므로 해당 검사만 끈다
@file:Suppress("ktlint:standard:no-unused-imports")

package {{base_package}}

import com.lemonappdev.konsist.api.Konsist
import com.lemonappdev.konsist.api.declaration.KoFileDeclaration
import com.lemonappdev.konsist.api.verify.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * ai-dev-harness 프로필 android-konsist의 고정 규칙(Konsist). 손으로 고치지 않는다(harness check가 드리프트를 본다).
 * 규칙을 끄려면 harness.json 영역의 disabled_rules에 "규칙 ID": "이유"를 적고 init --area --force로 다시 만든다.
 * 범위는 Konsist 프로젝트 루트(gradlew가 있는 Gradle 루트) 기준 디렉터리다. 테스트 소스는 보지 않는다.
 */
class HarnessFixedRulesTest {
    private val appDir = "{{app_dir}}"
    private val coreDir = "{{core_dir}}"
    private val featureDir = "{{feature_dir}}"
    private val wearDir = "{{wear_dir}}"
    private val production = Konsist.scopeFromProduction()

    private fun KoFileDeclaration.isIn(dir: String): Boolean = projectPath.replace('\\', '/').trimStart('/').startsWith("$dir/")

    private fun filesIn(vararg dirs: String): List<KoFileDeclaration> = production.files.filter { file -> dirs.any { file.isIn(it) } }

    private fun moduleFiles(): List<KoFileDeclaration> = filesIn(appDir, coreDir, featureDir, wearDir)

    @Test
    fun scopesAreNotEmpty() {
        // 경로 변수가 틀려 범위가 비면 아래 규칙이 모두 거짓 통과한다
        for (dir in listOf(appDir, coreDir, featureDir, wearDir)) {
            assertTrue("$dir 의 생산 소스를 찾지 못했다(Konsist 프로젝트 루트 기준 경로)", filesIn(dir).isNotEmpty())
        }
    }
    // harness:rule no-global-scope

    @Test
    fun noGlobalScope() {
        // 수명 없는 코루틴은 누수와 취소 누락을 만든다. viewModelScope·lifecycleScope처럼 수명 있는 범위를 쓴다
        // 주석·KDoc·문자열의 언급은 사용이 아니므로 지운 뒤 본다
        val commentsAndStrings = Regex("/\\*[\\s\\S]*?\\*/|//[^\\n]*|\"(?:\\\\.|[^\"\\\\\\n])*\"")
        val globalScope = Regex("\\bGlobalScope\\b")
        moduleFiles().assertFalse { file ->
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
        moduleFiles().assertFalse { file ->
            file.classes().any { it.name.endsWith("ViewModel") } &&
                file.imports.any { it.name in forbidden }
        }
    }
    // harness:end
    // harness:rule viewmodel-repository-only

    @Test
    fun viewModelUsesRepositoryOnly() {
        // ADR-04: ViewModel은 Repository 인터페이스만 의존한다. Retrofit·Room·DataSource·DAO는 data 계층 안에 숨긴다
        val forbiddenPackages = listOf("retrofit2.", "androidx.room.")
        val forbiddenSuffixes = listOf("DataSource", "Dao")
        moduleFiles().assertFalse { file ->
            file.classes().any { it.name.endsWith("ViewModel") } &&
                file.imports.any { imported ->
                    val simpleName = imported.name.substringAfterLast('.')
                    forbiddenPackages.any { imported.name.startsWith(it) } ||
                        forbiddenSuffixes.any { simpleName.endsWith(it) }
                }
        }
    }
    // harness:end
    // harness:rule screen-no-viewmodel-param

    @Test
    fun screenDoesNotTakeViewModel() {
        // *Screen은 상태와 콜백만 받는 무상태 Composable이다. ViewModel은 *Route에서 수집한다
        moduleFiles().assertFalse { file ->
            file.functions().any { function ->
                function.name.endsWith("Screen") &&
                    function.parameters.any { isViewModelType(it.type.name) }
            }
        }
    }

    private fun isViewModelType(name: String): Boolean = name.removeSuffix("?").endsWith("ViewModel")
    // harness:end
    // harness:rule usecase-shared-by-two-viewmodels

    @Test
    fun useCaseIsSharedByTwoViewModels() {
        // ADR-04: UseCase는 domain 패키지에 두고 2개 이상 ViewModel이 공유할 때만 만든다. 1회성 로직은 ViewModel·Repository에 둔다
        val viewModelFiles = moduleFiles().filter { file -> file.classes().any { it.name.endsWith("ViewModel") } }
        filesIn(featureDir).assertFalse { file ->
            val packageName = file.packagee?.name.orEmpty()
            val inDomain = "domain" in packageName.split('.')
            file.classes().any { useCase ->
                val usage = Regex("\\b${useCase.name}\\b")
                useCase.name.endsWith("UseCase") &&
                    (!inDomain || viewModelFiles.count { usage.containsMatchIn(it.text) } < 2)
            }
        }
    }
    // harness:end
    // harness:rule feature-no-room

    @Test
    fun featureDoesNotUseRoom() {
        // ADR-03: 폰 로컬 저장은 :core의 Workout 테이블만 Room을 쓴다. feature는 온라인 전용이다
        filesIn(featureDir).assertFalse { file ->
            file.imports.any { it.name.startsWith("androidx.room.") }
        }
    }
    // harness:end
    // harness:rule wear-no-network

    @Test
    fun wearDoesNotCallNetwork() {
        // ADR-02: 워치는 서버·인증을 모른다. 폰과는 Data Layer(DataClient·MessageClient)로만 주고받는다
        val forbiddenPackages = listOf("retrofit2.", "okhttp3.", "io.ktor.")
        filesIn(wearDir).assertFalse { file ->
            file.imports.any { imported -> forbiddenPackages.any { imported.name.startsWith(it) } }
        }
    }
    // harness:end
    // harness:rule app-no-data-layer

    @Test
    fun appDoesNotDeclareDataLayer() {
        // ADR-05: :app은 내비게이션·Hilt 루트·feature 조립만 한다. 데이터 계층은 feature·core에 둔다
        val forbiddenSuffixes = listOf("Repository", "DataSource", "Dao", "UseCase")
        filesIn(appDir).assertFalse { file ->
            val names = file.classes().map { it.name } + file.interfaces().map { it.name } + file.objects().map { it.name }
            names.any { name -> forbiddenSuffixes.any { name.endsWith(it) } }
        }
    }
    // harness:end
}
