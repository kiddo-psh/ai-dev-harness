import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import HomePage from './index';

/*
 * 화면 테스트는 실제 네트워크로 나가지 않는다. 공통 클라이언트를 대체해 두고, 화면이 도메인 함수를 쓰기
 * 시작하면 그 모듈(예: `vi.mock('/src/api/movies', ...)`)을 대체해 응답을 정한다.
 * 경로는 Vite 루트 기준이라 화면 깊이와 무관하다.
 */
vi.mock('/src/api/client', () => ({ request: vi.fn() }));

function renderPage() {
  const router = createMemoryRouter([{ path: '/', element: <HomePage /> }], {
    initialEntries: ['/'],
  });
  render(<RouterProvider router={router} />);
}

describe('HomePage', () => {
  it('화면 제목을 보여 준다', () => {
    renderPage();

    expect(screen.getByRole('heading', { level: 1, name: 'Home' })).toBeTruthy();
  });
});
