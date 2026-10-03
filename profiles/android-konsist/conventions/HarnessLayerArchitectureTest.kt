package {{base_package}}

import com.lemonappdev.konsist.api.Konsist
import com.lemonappdev.konsist.api.architecture.KoArchitectureCreator.assertArchitecture
import com.lemonappdev.konsist.api.architecture.Layer
import org.junit.Test

/**
 * ai-dev-harness 프로필 android-konsist의 계층 규칙(Konsist). 손으로 고치지 않는다(harness check가 드리프트를 본다).
 * harness.json 영역의 layers(계층 → 패키지 패턴)·allow(의존해도 되는 계층)에서 생성한다. allow에 없는 의존은 금지다.
 * 범위는 feature 모듈들(feature_dir 아래)의 생산 코드다. 바꾸려면 그 설정을 고친 뒤 init --area --force로 다시 만든다.
 */
class HarnessLayerArchitectureTest {
    @Test
    fun featureLayersDependOnlyOnAllowedLayers() {
        Konsist
            .scopeFromProduction()
            .slice { file -> file.projectPath.replace('\\', '/').trimStart('/').startsWith("{{feature_dir}}/") }
            .assertArchitecture {
{{konsist_layers}}

{{konsist_dependencies}}
            }
    }
}
