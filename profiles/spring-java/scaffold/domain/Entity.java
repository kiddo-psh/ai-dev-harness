package {{base_package}}.domain.{{name_lower}}.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

// API 계층에 노출하지 않는다. Lombok은 @Getter와 protected 기본 생성자로 제한한다(@Setter·@Builder·@Data 금지).
// 상태 변경은 의도가 드러나는 메서드로 한다. 테이블·컬럼은 스키마 문서와 마이그레이션에 맞춘다.
@Entity
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class {{name_pascal}} {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String name;

    private {{name_pascal}}(String name) {
        this.name = name;
    }

    public static {{name_pascal}} create(String name) {
        // 필수값·형식 검증을 여기에 둔다
        return new {{name_pascal}}(name);
    }
}
