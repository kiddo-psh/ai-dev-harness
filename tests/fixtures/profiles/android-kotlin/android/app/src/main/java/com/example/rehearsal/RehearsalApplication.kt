package com.example.rehearsal

import android.app.Application
import dagger.hilt.android.HiltAndroidApp

/**
 * 폰 앱의 Hilt 루트(ADR-06).
 */
@HiltAndroidApp
class RehearsalApplication : Application()
