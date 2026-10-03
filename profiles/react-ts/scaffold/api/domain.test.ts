import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get{{name_pascal}}, get{{name_pascal}}List } from './{{name_camel}}';

/*
 * 네트워크 대신 fetch를 대체한다. 화면에서는 드러나지 않는 것(경로, 메서드, 본문, 오류 처리)을 고정한다.
 */
const fetchMock = vi.fn();

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function requestedUrl(index = 0): string {
  return String((fetchMock.mock.calls[index] as [string, RequestInit])[0]);
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('{{name_camel}} API', () => {
  it('목록을 요청한다', async () => {
    fetchMock.mockResolvedValue(json(200, [{ id: 1 }]));

    await expect(get{{name_pascal}}List()).resolves.toEqual([{ id: 1 }]);
    expect(requestedUrl()).toMatch(/\/{{name_kebab}}$/);
  });

  it('항목 하나를 번호 경로로 요청한다', async () => {
    fetchMock.mockResolvedValue(json(200, { id: 7 }));

    await expect(get{{name_pascal}}(7)).resolves.toEqual({ id: 7 });
    expect(requestedUrl()).toMatch(/\/{{name_kebab}}\/7$/);
  });

  it('실패 응답이면 오류를 던진다', async () => {
    fetchMock.mockResolvedValue(json(500, { code: 'INTERNAL_ERROR' }));

    await expect(get{{name_pascal}}(7)).rejects.toThrow();
  });
});
