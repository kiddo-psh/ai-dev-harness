package {{base_package}}.architecture;

import static com.tngtech.archunit.library.Architectures.layeredArchitecture;

import com.tngtech.archunit.core.importer.ImportOption.DoNotIncludeTests;
import com.tngtech.archunit.junit.AnalyzeClasses;
import com.tngtech.archunit.junit.ArchTest;
import com.tngtech.archunit.lang.ArchRule;

// 하네스 계층 규칙. harness.json 영역의 layers(계층 → 패키지 패턴)·allow(의존해도 되는 계층)로 생성한다.
// 손으로 고치지 않는다. 계층을 바꾸려면 설정을 고친 뒤 init --area --force 로 다시 생성한다.
// allow 에 없는 계층 사이 의존은 금지다. 어느 계층에도 속하지 않는 클래스(global 등)는 보지 않는다.
@AnalyzeClasses(packages = "{{base_package}}", importOptions = DoNotIncludeTests.class)
class LayerRulesArchitectureTest {

    @ArchTest static final ArchRule CONFIGURED_LAYERS = configuredLayers();

    private static ArchRule configuredLayers() {
        return layeredArchitecture()
                .consideringOnlyDependenciesInLayers()
                .withOptionalLayers(true)
{{layer_definitions}}
{{layer_access_rules}}
                .allowEmptyShould(true);
    }
}
