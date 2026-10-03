/*
 * 공통 HTTP 클라이언트(최소).
 *
 * src/api/의 도메인 함수는 모두 이 모듈의 `{{api_client_fn}}()`을 거친다. 기본 경로, 헤더, 오류 변환을
 * 한곳에 둔다. 인증 토큰·재발급·재시도가 필요하면 이 파일에 더한다(생성 후 팀이 소유한다).
 *
 * 절대 URL을 쓰지 않는다. 개발에서는 Vite 개발 서버 프록시가, 배포에서는 리버스 프록시가 같은 출처로
 * 넘긴다고 가정한다.
 */

/** 모든 요청 경로 앞에 붙는다 */
const API_BASE = '/api/v1';

export type RequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  /** JSON으로 보낼 본문. 없으면 `Content-Type`을 붙이지 않는다 */
  body?: unknown;
};

/** 2xx가 아닌 응답. 상태 코드와 본문(JSON이면 객체)을 담는다 */
export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, body: unknown) {
    super(`API 요청이 실패했다: ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

/** API 요청 한 건. 본문이 없는 응답은 `undefined`로 돌려주므로 그런 API의 타입은 `void`로 둔다 */
export async function {{api_client_fn}}<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body } = options;
  const headers: Record<string, string> = { Accept: 'application/json' };

  if (body !== undefined) {
    headers['Content-Type'] = 'application/json; charset=utf-8';
  }

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'include',
  });
  const data = await parse(response);

  if (!response.ok) {
    throw new ApiError(response.status, data);
  }

  return data as T;
}

async function parse(response: Response): Promise<unknown> {
  const text = await response.text();

  if (!text) {
    return undefined;
  }

  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
