/*
 * 하네스 경계·접근성 규칙 (ai-dev-harness react-ts 프로필이 생성한 파일).
 *
 * 손으로 고치지 않는다. `harness check`가 드리프트를 본다. 계층 규칙은 harness.json 영역 설정의
 * `layers`·`allow`를, 고정 규칙 끄기는 `disabled_rules`(규칙 ID와 이유)를 고친 뒤
 * `harness init <저장소> --area <영역> --force`로 다시 만든다.
 *
 * 쓰는 법(eslint.config.js):
 *   import harness from './eslint.harness.js';
 *   export default [...기존 설정, ...harness];
 *
 * `no-restricted-imports`는 한 파일에 여러 설정 객체가 겹치면 마지막 객체의 옵션만 남는다. 그래서 이 파일은
 * 제한을 파일 묶음(디렉터리·깊이)마다 모아 설정 객체 하나로 만든다. 소비자 설정에서 이 파일 뒤에 같은 규칙을
 * 다시 켜면 여기 제한이 사라지므로 `...harness`를 배열 끝에 둔다.
 *
 * 검사 범위: 소스 루트 아래 상대 경로 import. 별칭 import(`@/...`)의 계층 방향과 테스트 파일은 보지 않는다.
 */

/** 영역 기준 소스 루트 */
const SRC_ROOT = '{{src_root}}';
/** 계층 이름 → 소스 루트 기준 디렉터리 목록 (harness.json `layers`) */
const LAYERS = {{layers_json}};
/** 계층 이름 → 의존해도 되는 계층 목록 (harness.json `allow`). 목록에 없는 의존은 금지 */
const ALLOW = {{allow_json}};

const SOURCE_FILES = '*.{js,jsx,ts,tsx}';
const TEST_FILES = ['**/*.test.*', '**/*.spec.*'];
/** 디렉터리 아래로 내려가며 검사할 최대 깊이 */
const MAX_DEPTH = 12;
const DIR_PATTERN = /^[A-Za-z0-9_-]+(\/[A-Za-z0-9_-]+)*$/;

/** 파일 묶음(glob) → no-restricted-imports 패턴 목록 */
const restrictions = new Map();
const configs = [];

function escapeRegex(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * 소스 루트 아래 `dir`의 파일마다 제한 패턴을 더한다.
 * `pattern(depth)`의 depth는 파일이 소스 루트에서 몇 단계 아래 디렉터리에 있는지다.
 * 상대 경로로 소스 루트에 닿으려면 `../`가 depth번 필요하다.
 */
function restrict(dir, pattern) {
  if (!DIR_PATTERN.test(dir)) {
    throw new Error(`eslint.harness.js: 디렉터리는 소스 루트 기준 상대 경로여야 한다: ${dir}`);
  }
  for (let extra = 0; extra <= MAX_DEPTH; extra += 1) {
    const glob = `${SRC_ROOT}/${dir}/${'*/'.repeat(extra)}${SOURCE_FILES}`;
    const depth = dir.split('/').length + extra;
    if (!restrictions.has(glob)) {
      restrictions.set(glob, []);
    }
    restrictions.get(glob).push(pattern(depth));
  }
}

/** 소스 루트까지 올라간 뒤 `dir`로 들어가는 상대 import */
function intoDir(depth, dir) {
  return `^(\\.\\./)${'{'}${depth}${'}'}${escapeRegex(dir)}(/|$)`;
}

// harness:rule no-mocks-import
for (const dir of ['pages', 'components']) {
  restrict(dir, () => ({
    regex: '(^|/)mocks(/|$)',
    message:
      '[no-mocks-import] 화면·공용 컴포넌트는 mocks/를 import하지 않는다. 데이터는 api/ 도메인 함수를 거친다.',
  }));
}
// harness:end

// harness:rule no-cross-screen-import
restrict('pages', (depth) => {
  // pages 루트까지는 `../`가 depth-1번이다. 그 안에서 올라갔다가 다른 *Page 디렉터리로 들어가면 다른 화면이다
  const climb = depth > 1 ? `(\\.\\./)${'{'}1,${depth - 1}${'}'}` : '(?!)';
  return {
    regex: `^${climb}([^./][^/]*/)*[A-Z][A-Za-z0-9]*Page(/|$)`,
    message:
      '[no-cross-screen-import] 다른 화면의 디렉터리(*Page/)를 import하지 않는다. 두 화면이 쓰면 components/로 올린다.',
  };
});
// harness:end

// 설정 규칙: harness.json `layers`·`allow`에서 만든 계층 방향
for (const [layer, dirs] of Object.entries(LAYERS)) {
  const allowed = new Set([layer, ...(ALLOW[layer] || [])]);
  const forbidden = Object.keys(LAYERS).filter((other) => !allowed.has(other));
  for (const dir of dirs) {
    restrict(dir, (depth) => ({
      regex: forbidden
        .flatMap((other) => LAYERS[other].map((target) => intoDir(depth, target)))
        .join('|') || '(?!)',
      message: `[layers] 계층 ${layer}은 ${forbidden.join(', ') || '(없음)'}에 의존하지 않는다. 허용: ${
        [...allowed].filter((name) => name !== layer).join(', ') || '(없음)'
      } (harness.json allow.${layer})`,
    }));
  }
}

// harness:rule jsx-a11y-recommended
import jsxA11y from 'eslint-plugin-jsx-a11y';

configs.push({
  ...jsxA11y.flatConfigs.recommended,
  files: [`${SRC_ROOT}/**/*.{jsx,tsx}`],
});
// harness:end

for (const [glob, patterns] of restrictions) {
  configs.push({
    files: [glob],
    ignores: TEST_FILES,
    rules: {
      'no-restricted-imports': ['error', { patterns }],
    },
  });
}

export default configs;
