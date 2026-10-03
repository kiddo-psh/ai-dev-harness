package {{base_package}}.domain.{{name_lower}}.repository;

import {{base_package}}.domain.{{name_lower}}.entity.{{name_pascal}};
import org.springframework.data.jpa.repository.JpaRepository;

// 영속성 조회·저장만 담당한다. 비즈니스 판단·외부 호출·트랜잭션 선언을 두지 않는다.
public interface {{name_pascal}}Repository extends JpaRepository<{{name_pascal}}, Long> {}
