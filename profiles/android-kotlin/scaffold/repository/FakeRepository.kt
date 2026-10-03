package {{base_package}}.feature.{{feature}}.data

/**
 * ViewModel 단위 테스트에서 생성자로 넘기는 대역(Hilt 없이, ADR-06).
 */
class Fake{{name_pascal}}Repository(
    var items: List<String> = emptyList(),
) : {{name_pascal}}Repository {
    override suspend fun load(): List<String> = items
}
