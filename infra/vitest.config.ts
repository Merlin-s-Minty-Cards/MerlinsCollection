import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'node',
    include: ['test/**/*.test.ts'],
    // backend-stack.test.ts's beforeAll does one real `docker build`
    // (DockerImageCode.fromImageAsset) — its own hook passes an explicit
    // 300_000ms timeout for that; this default covers everything else.
    testTimeout: 20_000,
  },
})
