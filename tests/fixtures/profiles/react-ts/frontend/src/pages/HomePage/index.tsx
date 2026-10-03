/*
 * Home 화면.
 *
 * 라우트 등록은 `harness scaffold`가 출력한 조각을 routes/paths.ts · routes/router.tsx에 붙인다.
 * 데이터는 src/api/의 도메인 함수로 부른다. mocks/와 다른 화면의 하위 컴포넌트는 import하지 않는다
 * (eslint.harness.js). 이 화면에서만 쓰는 하위 컴포넌트는 이 디렉터리 아래에 둔다.
 */
import styles from './HomePage.module.css';

export default function HomePage() {
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Home</h1>
    </main>
  );
}
