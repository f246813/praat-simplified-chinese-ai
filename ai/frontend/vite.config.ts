import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
export default defineConfig({
  base: './', plugins: [react()],
  server: { hmr: false }, // no inline React-refresh preamble; retain strict script CSP
  // Keep dependency semantics intact and avoid pathological barrel graph tree-shaking.
  // Larger offline bundle is intentional; no vendor runtime or feature is removed.
  build: { target: 'es2022', assetsInlineLimit: 0, sourcemap: false, rollupOptions: {treeshake: false} },
  test: { environment: 'jsdom', include: ['tests/**/*.test.{ts,tsx}'], restoreMocks: true },
});
