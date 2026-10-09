import { fileURLToPath } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

/* Test semantics match the deployment repo (joveo/coder-pets-tray), whose CI gates on the
   coverage thresholds below. The tests live HERE because ops/sync_to_deploy.py mirrors src/
   downstream and deletes what does not exist upstream. Server tests (PGlite, node:crypto,
   Next server APIs) opt into `// @vitest-environment node` on their first line. */
export default defineConfig({
  plugins: [react()],
  resolve: {
    /* Vite does not read tsconfig `paths`. Every import under src/ uses `@/...`. */
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    exclude: ['node_modules/**', '.next/**'],
    // Every hash is real scrypt at N=2^17, which is the point -- and ~100-300ms each.
    testTimeout: 30_000,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json-summary', 'lcov', 'html'],
      reportsDirectory: './coverage',
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/**/*.test.{ts,tsx}',
        'src/**/*.d.ts',
        'src/app/**/layout.tsx',
        'src/app/**/loading.tsx',
        'src/app/**/error.tsx',
        'src/app/**/not-found.tsx',

        /* Pure type declarations -- TypeScript erases the whole file, so there is no
           runtime code to execute. `next build` type-checks it, which is a strictly
           stronger check than line coverage could ever be. */
        'src/types.ts',

        /* Vendored UI primitive (Origin UI / shadcn convention), consumed only by the
           /simulator stub page and exercised by Playwright downstream. It cannot reach 80%
           branches under jsdom by construction: it branches on NODE_ENV === 'production'
           (never true in test), calls matches(':focus-visible') (inconsistent in jsdom),
           and sizes itself from getBoundingClientRect(), which returns all zeros. */
        'src/components/ui/**',
      ],
      thresholds: {
        lines: 80,
        functions: 80,
        branches: 80,
        statements: 80,
      },
    },
    restoreMocks: true,
    clearMocks: true,
  },
});
