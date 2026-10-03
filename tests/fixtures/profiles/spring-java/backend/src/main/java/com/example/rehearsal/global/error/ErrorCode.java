package com.example.rehearsal.global.error;

import lombok.Getter;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;

// 공통 오류 코드(스캐폴드 Service의 주석 예시가 가리키는 위치)
@Getter
@RequiredArgsConstructor
public enum ErrorCode {
    NOT_FOUND(HttpStatus.NOT_FOUND, "리소스를 찾을 수 없다");

    private final HttpStatus status;
    private final String message;
}
