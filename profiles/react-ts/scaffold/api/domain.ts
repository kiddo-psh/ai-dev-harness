/*
 * {{name_camel}} API 접근 함수.
 *
 * 공통 클라이언트의 `{{api_client_fn}}()`만 거친다. 기본 경로·인증·오류 변환은 클라이언트가 맡는다.
 * 함수마다 위에 계약 문서의 API ID를 적는다(`// API-ID: API-012`). 화면은 이 함수만 부르고
 * mocks/를 직접 import하지 않는다. 응답 타입이 여러 모듈에서 쓰이면 src/types/로 옮긴다.
 */
import { {{api_client_fn}} } from '{{api_client_import}}';

/** 응답 한 항목. 계약 문서의 응답 모양으로 바꾼다 */
export type {{name_pascal}} = {
  id: number;
};

// API-ID: (계약의 API ID)
export async function get{{name_pascal}}List(): Promise<{{name_pascal}}[]> {
  return {{api_client_fn}}<{{name_pascal}}[]>('/{{name_kebab}}');
}

// API-ID: (계약의 API ID)
export async function get{{name_pascal}}(id: number): Promise<{{name_pascal}}> {
  return {{api_client_fn}}<{{name_pascal}}>(`/{{name_kebab}}/${id}`);
}
