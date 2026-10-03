package {{base_package}}.domain.{{name_lower}}.service;

import {{base_package}}.domain.{{name_lower}}.dto.request.{{name_pascal}}CreateRequest;
import {{base_package}}.domain.{{name_lower}}.dto.response.{{name_pascal}}Response;
import {{base_package}}.domain.{{name_lower}}.entity.{{name_pascal}};
import {{base_package}}.domain.{{name_lower}}.repository.{{name_pascal}}Repository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

// 유스케이스와 트랜잭션 경계를 담당한다. 클래스는 읽기 전용이고 쓰기 메서드에서 @Transactional로 덮어쓴다.
// Servlet API·ResponseEntity 같은 HTTP 표현에 의존하지 않는다.
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class {{name_pascal}}Service {

    private final {{name_pascal}}Repository {{name_camel}}Repository;

    public {{name_pascal}}Response get(Long id) {
        // 없는 리소스는 프로젝트 공통 예외로 바꾼다. 예: throw new BusinessException(ErrorCode.<코드>)
        // (BusinessException·ErrorCode 위치: {{error_package}}). 도메인 전용 예외 클래스는 만들지 않는다.
        {{name_pascal}} {{name_camel}} = {{name_camel}}Repository.findById(id).orElseThrow();
        return {{name_pascal}}Response.from({{name_camel}});
    }

    @Transactional
    public {{name_pascal}}Response create({{name_pascal}}CreateRequest request) {
        {{name_pascal}} saved = {{name_camel}}Repository.save({{name_pascal}}.create(request.name()));
        return {{name_pascal}}Response.from(saved);
    }
}
