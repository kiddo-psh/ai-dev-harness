package {{base_package}}.feature.{{feature}}.di

import {{base_package}}.feature.{{feature}}.data.Default{{name_pascal}}Repository
import {{base_package}}.feature.{{feature}}.data.{{name_pascal}}Repository
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent

/**
 * feature가 자기 Repository 바인딩을 제공한다(ADR-06). 테스트에서 바꿔치기하려면 @TestInstallIn으로 이 모듈을 대체한다.
 */
@Module
@InstallIn(SingletonComponent::class)
abstract class {{name_pascal}}RepositoryModule {
    @Binds
    abstract fun bind{{name_pascal}}Repository(repository: Default{{name_pascal}}Repository): {{name_pascal}}Repository
}
