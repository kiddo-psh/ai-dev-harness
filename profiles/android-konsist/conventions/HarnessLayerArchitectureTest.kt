package {{base_package}}

import com.lemonappdev.konsist.api.Konsist
import com.lemonappdev.konsist.api.architecture.KoArchitectureCreator.assertArchitecture
import com.lemonappdev.konsist.api.architecture.Layer
import com.lemonappdev.konsist.api.declaration.KoFileDeclaration
import org.junit.Test

/**
 * ai-dev-harness 프로필 android-konsist의 계층 규칙(Konsist). 손으로 고치지 않는다(harness check가 드리프트를 본다).
 * harness.json 영역의 layers(계층 → 패키지 패턴)·allow(의존해도 되는 계층)에서 생성한다. allow에 없는 계층 의존은 금지다.
 * Konsist의 dependsOn은 "의존해도 된다"만 뜻하므로 나머지 계층은 doesNotDependOn으로 따로 막는다.
 * 범위는 feature 모듈들(feature_dir 아래)의 생산 코드다. 바꾸려면 그 설정을 고친 뒤 init --area --force로 다시 만든다.
 */
class HarnessLayerArchitectureTest {
    @Test
    fun featureLayersDependOnlyOnAllowedLayers() {
        // 계층 이름 → Konsist 계층. Konsist는 같은 이름의 Layer 인스턴스가 둘이면 중복으로 보므로 한 번만 만든다
        val layers: Map<String, Layer> =
            mapOf(
{{konsist_layers}}
            )
        // 계층 이름 → 의존해도 되는 계층 이름(allow)
        val allowed: Map<String, List<String>> =
            mapOf(
{{konsist_allowed}}
            )
        Konsist
            .scopeFromProduction()
            .slice { isInFeature(it) }
            .assertArchitecture(testName = "featureLayersDependOnlyOnAllowedLayers") {
                for ((name, layer) in layers) {
                    val targets = allowed.getValue(name).map { layers.getValue(it) }.toSet()
                    val others = layers.values.toSet() - targets - layer
                    if (targets.isEmpty()) {
                        layer.dependsOnNothing()
                    } else {
                        layer.dependsOn(targets)
                        if (others.isNotEmpty()) {
                            layer.doesNotDependOn(others)
                        }
                    }
                }
            }
    }

    private fun isInFeature(file: KoFileDeclaration): Boolean {
        val path = file.projectPath.replace('\\', '/')
        return path.trimStart('/').startsWith("{{feature_dir}}/")
    }
}
