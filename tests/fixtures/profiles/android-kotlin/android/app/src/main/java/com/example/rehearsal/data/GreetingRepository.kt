package com.example.rehearsal.data

import com.example.rehearsal.domain.Greeting

/**
 * 계층 기본값의 data 계층 자리. data → domain 의존은 허용된다.
 */
class GreetingRepository {
    fun greeting(): Greeting = Greeting(text = "Hello")
}
