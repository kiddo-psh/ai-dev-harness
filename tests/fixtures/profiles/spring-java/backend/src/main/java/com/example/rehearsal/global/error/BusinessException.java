package com.example.rehearsal.global.error;

import lombok.Getter;

// 공통 비즈니스 예외. 도메인 전용 예외 클래스는 만들지 않는다
@Getter
public class BusinessException extends RuntimeException {

    private final ErrorCode errorCode;

    public BusinessException(ErrorCode errorCode) {
        super(errorCode.getMessage());
        this.errorCode = errorCode;
    }
}
