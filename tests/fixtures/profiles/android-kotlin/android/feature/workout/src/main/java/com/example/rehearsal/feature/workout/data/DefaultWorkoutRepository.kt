package com.example.rehearsal.feature.workout.data

import com.example.rehearsal.core.model.WorkoutSet
import javax.inject.Inject

class DefaultWorkoutRepository
    @Inject
    constructor() : WorkoutRepository {
        override suspend fun sets(): List<WorkoutSet> = listOf(WorkoutSet(weightKg = 60, reps = 10))
    }
