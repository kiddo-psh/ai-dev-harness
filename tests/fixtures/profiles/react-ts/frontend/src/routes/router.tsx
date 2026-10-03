// 리허설 스크립트가 `harness scaffold screen` 조각을 아래 표식 자리에 붙인다
import { createBrowserRouter } from 'react-router';
import HomePage from '../pages/HomePage';
// rehearsal:import
import { ROUTE_PATTERN } from './paths';

export const router = createBrowserRouter([
  { path: ROUTE_PATTERN.home, element: <HomePage /> },
  // rehearsal:route
]);
