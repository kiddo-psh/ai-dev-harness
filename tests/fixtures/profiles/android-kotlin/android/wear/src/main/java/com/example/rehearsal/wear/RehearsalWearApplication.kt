package com.example.rehearsal.wear

import android.app.Application
import dagger.hilt.android.HiltAndroidApp

/**
 * 워치 앱의 Hilt 루트(ADR-06). 워치는 :core만 의존한다(ADR-05).
 */
@HiltAndroidApp
class RehearsalWearApplication : Application()
