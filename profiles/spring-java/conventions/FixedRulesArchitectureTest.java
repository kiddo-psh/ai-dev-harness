package {{base_package}}.architecture;

import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.classes;
import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.methods;
import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noClasses;
import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noFields;
import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noMethods;
import static com.tngtech.archunit.library.dependencies.SlicesRuleDefinition.slices;

import com.tngtech.archunit.core.domain.Dependency;
import com.tngtech.archunit.core.domain.JavaClass;
import com.tngtech.archunit.core.domain.JavaMethod;
import com.tngtech.archunit.core.importer.ImportOption.DoNotIncludeTests;
import com.tngtech.archunit.junit.AnalyzeClasses;
import com.tngtech.archunit.junit.ArchTest;
import com.tngtech.archunit.lang.ArchCondition;
import com.tngtech.archunit.lang.ArchRule;
import com.tngtech.archunit.lang.CompositeArchRule;
import com.tngtech.archunit.lang.ConditionEvents;
import com.tngtech.archunit.lang.SimpleConditionEvent;

// 하네스 고정 규칙. harness init 이 생성하고 harness check 가 드리프트를 본다. 손으로 고치지 않는다.
// 규칙을 끄려면 harness.json 영역의 disabled_rules 에 "규칙 ID": "이유"를 적고 init --area --force 로
// 다시 생성한다. 규칙 정의는 아래 메서드에 있고, 끄면 그 규칙의 필드만 빠진다.
/** 규칙마다 {@link ArchTest} 필드 하나. */
@AnalyzeClasses(packages = "{{base_package}}", importOptions = DoNotIncludeTests.class)
class FixedRulesArchitectureTest {

    private static final String CONTROLLER = "..controller..";
    private static final String SERVICE = "..service..";
    private static final String SPRING_TRANSACTIONAL =
            "org.springframework.transaction.annotation.Transactional";
    private static final String JAKARTA_TRANSACTIONAL = "jakarta.transaction.Transactional";
    private static final String AUTOWIRED =
            "org.springframework.beans.factory.annotation.Autowired";
    private static final String INJECT = "jakarta.inject.Inject";
    private static final String ENTITY = "jakarta.persistence.Entity";
    private static final String RESPONSE_ENTITY = "org.springframework.http.ResponseEntity";
    private static final String DOMAIN = "{{base_package}}.domain..";
    private static final String DOMAIN_PREFIX = "{{base_package}}.domain.";
    private static final String EVENT_PUBLISHER =
            "org.springframework.context.ApplicationEventPublisher";
    // harness:rule transactional-in-service-only

    @ArchTest static final ArchRule TRANSACTIONAL_IN_SERVICE_ONLY = transactionalInServiceOnly();

    // harness:end
    // harness:rule controller-no-entity-return

    @ArchTest static final ArchRule CONTROLLER_NO_ENTITY_RETURN = controllerNoEntityReturn();

    // harness:end
    // harness:rule no-field-injection

    @ArchTest static final ArchRule NO_FIELD_INJECTION = noFieldInjection();

    // harness:end
    // harness:rule service-no-web-types

    @ArchTest static final ArchRule SERVICE_NO_WEB_TYPES = serviceNoWebTypes();

    // harness:end
    // harness:rule no-service-cycle-between-domains

    @ArchTest static final ArchRule NO_DOMAIN_SERVICE_CYCLE = noDomainServiceCycle();

    // harness:end
    // harness:rule no-cross-domain-persistence

    @ArchTest static final ArchRule NO_CROSS_DOMAIN_PERSISTENCE = noCrossDomainPersistence();

    // harness:end
    // harness:rule event-publisher-in-service-only

    @ArchTest static final ArchRule EVENT_PUBLISHER_IN_SERVICE_ONLY = eventPublisherInServiceOnly();

    // harness:end

    private static ArchRule transactionalInServiceOnly() {
        ArchRule classes =
                noClasses()
                        .that()
                        .resideOutsideOfPackage(SERVICE)
                        .should()
                        .beAnnotatedWith(SPRING_TRANSACTIONAL)
                        .orShould()
                        .beAnnotatedWith(JAKARTA_TRANSACTIONAL);
        ArchRule methods =
                noMethods()
                        .that()
                        .areDeclaredInClassesThat()
                        .resideOutsideOfPackage(SERVICE)
                        .should()
                        .beAnnotatedWith(SPRING_TRANSACTIONAL)
                        .orShould()
                        .beAnnotatedWith(JAKARTA_TRANSACTIONAL);
        return CompositeArchRule.of(classes)
                .and(methods)
                .because("트랜잭션 경계는 유스케이스 Service가 소유한다")
                .allowEmptyShould(true);
    }

    private static ArchRule controllerNoEntityReturn() {
        return methods()
                .that()
                .areDeclaredInClassesThat()
                .resideInAPackage(CONTROLLER)
                .and()
                .arePublic()
                .should(notReturnEntities())
                .because("Controller는 엔티티 대신 응답 DTO를 반환한다")
                .allowEmptyShould(true);
    }

    private static ArchRule noFieldInjection() {
        return noFields()
                .should()
                .beAnnotatedWith(AUTOWIRED)
                .orShould()
                .beAnnotatedWith(INJECT)
                .because("의존성은 생성자로 주입하고 필드를 final로 둔다")
                .allowEmptyShould(true);
    }

    private static ArchRule serviceNoWebTypes() {
        return noClasses()
                .that()
                .resideInAPackage(SERVICE)
                .should()
                .dependOnClassesThat()
                .resideInAPackage("jakarta.servlet..")
                .orShould()
                .dependOnClassesThat()
                .haveFullyQualifiedName(RESPONSE_ENTITY)
                .because("Service는 HTTP 표현(Servlet API, ResponseEntity)에 의존하지 않는다")
                .allowEmptyShould(true);
    }

    private static ArchRule noDomainServiceCycle() {
        return slices().matching("{{base_package}}.domain.(*).service..")
                .should()
                .beFreeOfCycles()
                .because("기능 사이 Service 순환은 유스케이스 경계나 이벤트로 다시 설계한다")
                .allowEmptyShould(true);
    }

    private static ArchRule noCrossDomainPersistence() {
        return classes()
                .that()
                .resideInAPackage(DOMAIN)
                .should(notDependOnOtherDomainPersistence())
                .because("다른 기능의 상태는 이벤트로 바꾸고 그 기능의 public service로 읽는다")
                .allowEmptyShould(true);
    }

    private static ArchRule eventPublisherInServiceOnly() {
        return noClasses()
                .that()
                .resideInAPackage(DOMAIN)
                .and()
                .resideOutsideOfPackage(SERVICE)
                .should()
                .dependOnClassesThat()
                .haveFullyQualifiedName(EVENT_PUBLISHER)
                .because("도메인 이벤트는 유스케이스 Service가 발행한다")
                .allowEmptyShould(true);
    }

    private static ArchCondition<JavaMethod> notReturnEntities() {
        return new ArchCondition<>("not return @Entity types") {
            @Override
            public void check(JavaMethod method, ConditionEvents events) {
                for (JavaClass type : method.getReturnType().getAllInvolvedRawTypes()) {
                    if (type.isAnnotatedWith(ENTITY)) {
                        events.add(SimpleConditionEvent.violated(method, describe(method, type)));
                    }
                }
            }
        };
    }

    private static ArchCondition<JavaClass> notDependOnOtherDomainPersistence() {
        return new ArchCondition<>("not depend on another domain's repository or entity") {
            @Override
            public void check(JavaClass origin, ConditionEvents events) {
                String own = domainOf(origin.getPackageName());
                for (Dependency dependency : origin.getDirectDependenciesFromSelf()) {
                    String targetPackage = dependency.getTargetClass().getPackageName();
                    String target = domainOf(targetPackage);
                    if (target == null || target.equals(own) || !isPersistence(targetPackage)) {
                        continue;
                    }
                    events.add(
                            SimpleConditionEvent.violated(dependency, dependency.getDescription()));
                }
            }
        };
    }

    /** {@code <base_package>.domain.<기능>...} 의 기능 이름. 도메인 패키지 밖이면 null. */
    private static String domainOf(String packageName) {
        if (!packageName.startsWith(DOMAIN_PREFIX)) {
            return null;
        }
        String rest = packageName.substring(DOMAIN_PREFIX.length());
        int dot = rest.indexOf('.');
        return dot < 0 ? rest : rest.substring(0, dot);
    }

    private static boolean isPersistence(String packageName) {
        String dotted = "." + packageName + ".";
        return dotted.contains(".repository.") || dotted.contains(".entity.");
    }

    private static String describe(JavaMethod method, JavaClass type) {
        return method.getFullName() + " 이 엔티티 " + type.getName() + " 을 반환한다";
    }
}
