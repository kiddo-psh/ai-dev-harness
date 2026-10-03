package com.example.rehearsal.feature.workout.ui.complete

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.rehearsal.feature.workout.domain.WorkoutVolumeUseCase
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class WorkoutCompleteViewModel
    @Inject
    constructor(
        private val workoutVolume: WorkoutVolumeUseCase,
    ) : ViewModel() {
        private val _volume = MutableStateFlow(0)
        val volume: StateFlow<Int> = _volume.asStateFlow()

        fun refresh() {
            viewModelScope.launch {
                _volume.value = workoutVolume()
            }
        }
    }
