package com.example.rehearsal.feature.workout.data

import com.example.rehearsal.core.model.WorkoutSet

/**
 * 리허설 fixture: feature 계층 규칙의 data 계층 자리(ADR-04).
 */
interface WorkoutRepository {
    suspend fun sets(): List<WorkoutSet>
}
