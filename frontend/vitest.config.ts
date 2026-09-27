import { fileURLToPath } from 'node:url';

import { defineConfig } from 'vitest/config';

export default defineConfig({
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
    // Every hash is real scrypt at N=2^17, which is the point -- and ~100-300ms each.
    testTimeout: 30_000,
  },
});
