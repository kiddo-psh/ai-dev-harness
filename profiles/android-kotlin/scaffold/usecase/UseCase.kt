package {{base_package}}.feature.{{feature}}.domain

import javax.inject.Inject

/**
 * 2개 이상 ViewModel이 공유하는 로직만 UseCase로 둔다(ADR-04, 규칙 usecase-shared-by-two-viewmodels).
 * 사용하는 ViewModel이 둘이 되기 전에는 컨벤션 테스트가 실패한다. PR 설명에 사용처 2곳을 적는다.
 * 1회성 로직은 ViewModel 또는 Repository에 둔다. 의존은 data 계층(Repository 인터페이스)만 받는다.
 */
class {{name_pascal}}UseCase
    @Inject
    constructor() {
        operator fun invoke(): List<String> = emptyList()
    }
