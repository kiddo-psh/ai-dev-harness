package {{base_package}}.domain.{{name_lower}}.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.BDDMockito.given;
import static org.mockito.BDDMockito.then;

import {{base_package}}.domain.{{name_lower}}.dto.request.{{name_pascal}}CreateRequest;
import {{base_package}}.domain.{{name_lower}}.dto.response.{{name_pascal}}Response;
import {{base_package}}.domain.{{name_lower}}.entity.{{name_pascal}};
import {{base_package}}.domain.{{name_lower}}.repository.{{name_pascal}}Repository;
import java.util.NoSuchElementException;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

// Service 단위 테스트(Mockito). 플랜의 인수 테스트 목록에 맞춰 이름과 기대값을 바꾼다.
@ExtendWith(MockitoExtension.class)
class {{name_pascal}}ServiceTest {

    @Mock private {{name_pascal}}Repository {{name_camel}}Repository;

    @InjectMocks private {{name_pascal}}Service {{name_camel}}Service;

    @Test
    void createSavesEntityAndReturnsResponse() {
        given({{name_camel}}Repository.save(any({{name_pascal}}.class)))
                .willAnswer(invocation -> invocation.getArgument(0));

        {{name_pascal}}Response response =
                {{name_camel}}Service.create(new {{name_pascal}}CreateRequest("sample"));

        assertThat(response.name()).isEqualTo("sample");
        then({{name_camel}}Repository).should().save(any({{name_pascal}}.class));
    }

    @Test
    void getFailsWhenMissing() {
        given({{name_camel}}Repository.findById(1L)).willReturn(Optional.empty());

        // 공통 예외(BusinessException)로 바꾸면 기대 예외도 함께 바꾼다
        assertThatThrownBy(() -> {{name_camel}}Service.get(1L))
                .isInstanceOf(NoSuchElementException.class);
    }
}
