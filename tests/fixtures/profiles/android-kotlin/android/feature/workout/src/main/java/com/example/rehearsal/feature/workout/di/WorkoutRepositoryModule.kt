package com.example.rehearsal.feature.workout.di

import com.example.rehearsal.feature.workout.data.DefaultWorkoutRepository
import com.example.rehearsal.feature.workout.data.WorkoutRepository
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent

@Module
@InstallIn(SingletonComponent::class)
abstract class WorkoutRepositoryModule {
    @Binds
    abstract fun bindWorkoutRepository(repository: DefaultWorkoutRepository): WorkoutRepository
}
