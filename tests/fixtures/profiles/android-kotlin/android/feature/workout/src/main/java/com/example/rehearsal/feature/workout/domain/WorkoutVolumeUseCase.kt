package com.example.rehearsal.feature.workout.domain

import com.example.rehearsal.feature.workout.data.WorkoutRepository
import javax.inject.Inject

/**
 * 리허설 fixture: 두 ViewModel(세션·완료 화면)이 공유하는 로직이라 UseCase로 둔다(ADR-04, 규칙 usecase-shared-by-two-viewmodels).
 */
class WorkoutVolumeUseCase
    @Inject
    constructor(
        private val repository: WorkoutRepository,
    ) {
        suspend operator fun invoke(): Int = repository.sets().sumOf { it.weightKg * it.reps }
    }
