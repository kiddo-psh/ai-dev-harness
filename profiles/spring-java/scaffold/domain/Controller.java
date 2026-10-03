package {{base_package}}.domain.{{name_lower}}.controller;

import {{base_package}}.domain.{{name_lower}}.dto.request.{{name_pascal}}CreateRequest;
import {{base_package}}.domain.{{name_lower}}.dto.response.{{name_pascal}}Response;
import {{base_package}}.domain.{{name_lower}}.service.{{name_pascal}}Service;
import java.net.URI;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

// HTTP 경계만 담당한다. 경로·상태 코드·오류 응답은 API 명세를 따르고, 엔티티 대신 응답 DTO를 반환한다.
// 요청 검증(@Valid)은 Bean Validation 의존성이 있으면 요청 DTO와 함께 추가한다.
@RestController
@RequestMapping("/api/v1/{{name_kebab}}")
@RequiredArgsConstructor
public class {{name_pascal}}Controller {

    private final {{name_pascal}}Service {{name_camel}}Service;

    @GetMapping("/{id}")
    public {{name_pascal}}Response get(@PathVariable("id") Long id) {
        return {{name_camel}}Service.get(id);
    }

    @PostMapping
    public ResponseEntity<{{name_pascal}}Response> create(
            @RequestBody {{name_pascal}}CreateRequest request) {
        {{name_pascal}}Response response = {{name_camel}}Service.create(request);
        return ResponseEntity.created(URI.create("/api/v1/{{name_kebab}}/" + response.id()))
                .body(response);
    }
}
