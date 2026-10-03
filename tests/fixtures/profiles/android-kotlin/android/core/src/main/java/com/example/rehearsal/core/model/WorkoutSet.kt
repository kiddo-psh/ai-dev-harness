package com.example.rehearsal.core.model

/**
 * 폰·워치가 공유하는 순수 Kotlin 모델(ADR-04: 모델은 :core).
 */
data class WorkoutSet(
    val weightKg: Int,
    val reps: Int,
)
