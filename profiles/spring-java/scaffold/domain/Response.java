package {{base_package}}.domain.{{name_lower}}.dto.response;

import {{base_package}}.domain.{{name_lower}}.entity.{{name_pascal}};

// 엔티티 하나를 단순 변환하면 from 정적 팩토리를 쓴다. 여러 엔티티를 조립하면 도메인 mapper를 둔다.
public record {{name_pascal}}Response(Long id, String name) {

    public static {{name_pascal}}Response from({{name_pascal}} {{name_camel}}) {
        return new {{name_pascal}}Response({{name_camel}}.getId(), {{name_camel}}.getName());
    }
}
