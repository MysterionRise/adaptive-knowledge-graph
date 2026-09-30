import { defineConfig, globalIgnores } from 'eslint/config';
import nextCoreWebVitals from 'eslint-config-next/core-web-vitals';

// Flat config replacing the legacy .eslintrc.json (`next lint` was removed in Next.js 16).
export default defineConfig([
  ...nextCoreWebVitals,
  {
    rules: {
      'react/no-unescaped-entities': 'off',
      '@next/next/no-page-custom-font': 'off',
    },
  },
  {
    // eslint-plugin-react-hooks v7 (bundled with eslint-config-next 16) adds React Compiler
    // rules that the previous config did not have. Existing components trip these three, so
    // they are reported as warnings until the components are refactored; then remove this block
    // to restore the preset's `error` level.
    files: ['app/**', 'components/**'],
    rules: {
      'react-hooks/set-state-in-effect': 'warn',
      'react-hooks/refs': 'warn',
      'react-hooks/immutability': 'warn',
    },
  },
  globalIgnores([
    '.next/**',
    'out/**',
    'build/**',
    'coverage/**',
    'playwright-report/**',
    'test-results/**',
    'next-env.d.ts',
  ]),
]);
