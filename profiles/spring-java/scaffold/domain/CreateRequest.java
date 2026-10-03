package {{base_package}}.domain.{{name_lower}}.dto.request;

// 요청 검증 애너테이션(Bean Validation)은 요청 DTO에 둔다.
public record {{name_pascal}}CreateRequest(String name) {}
