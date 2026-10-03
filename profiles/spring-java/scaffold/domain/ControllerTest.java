package {{base_package}}.domain.{{name_lower}}.controller;

import static org.mockito.BDDMockito.given;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import {{base_package}}.domain.{{name_lower}}.dto.request.{{name_pascal}}CreateRequest;
import {{base_package}}.domain.{{name_lower}}.dto.response.{{name_pascal}}Response;
import {{base_package}}.domain.{{name_lower}}.service.{{name_pascal}}Service;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.TestConfiguration;
import {{webmvc_test_package}}.AutoConfigureMockMvc;
import {{webmvc_test_package}}.WebMvcTest;
import org.springframework.context.annotation.Bean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

// Controller 슬라이스 테스트. Service 대역은 @MockBean(Boot 4.x 제거)·@MockitoBean(Boot 3.4+) 대신
// @TestConfiguration의 Mockito 빈으로 준다(Boot 3.x·4.x 공통). 보안 필터는 끄고 인가는 별도 테스트로 본다.
@WebMvcTest({{name_pascal}}Controller.class)
@AutoConfigureMockMvc(addFilters = false)
class {{name_pascal}}ControllerTest {

    @Autowired private MockMvc mockMvc;

    @Autowired private {{name_pascal}}Service {{name_camel}}Service;

    @AfterEach
    void resetMocks() {
        Mockito.reset({{name_camel}}Service);
    }

    @Test
    void getReturnsResponse() throws Exception {
        given({{name_camel}}Service.get(1L)).willReturn(new {{name_pascal}}Response(1L, "sample"));

        mockMvc.perform(get("/api/v1/{{name_kebab}}/{id}", 1L))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.name").value("sample"));
    }

    @Test
    void createReturnsCreated() throws Exception {
        given({{name_camel}}Service.create(new {{name_pascal}}CreateRequest("sample")))
                .willReturn(new {{name_pascal}}Response(1L, "sample"));

        mockMvc.perform(
                        post("/api/v1/{{name_kebab}}")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"name\":\"sample\"}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").value(1));
    }

    @TestConfiguration
    static class ServiceMockConfig {

        @Bean
        {{name_pascal}}Service {{name_camel}}Service() {
            return Mockito.mock({{name_pascal}}Service.class);
        }
    }
}
