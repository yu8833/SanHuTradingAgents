/// <reference types="vitest" />
import { defineConfig } from 'vite'
import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig({
  plugins: [
    vue(),
    AutoImport({
      resolvers: [ElementPlusResolver()],
      imports: ['vue', 'vue-router', 'pinia'],
      dts: false,
    }),
    Components({
      resolvers: [ElementPlusResolver()],
      dts: false,
    }),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  // ---- Vitest 配置 ----
  test: {
    environment: 'happy-dom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/**/*.{test,spec}.{ts,js}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html', 'lcov'],
      reportsDirectory: './tests/coverage',
      // 覆盖率门槛：初始 5%，后续逐步提升
      lines: 5,
      functions: 5,
      branches: 5,
      statements: 5,
      // 只统计 src/ 目录
      include: ['src/**/*.{ts,vue,js}'],
      exclude: [
        'src/main.ts',
        'src/**/*.d.ts',
        'src/vite-env.d.ts',
        'tests/**',
      ],
    },
    testTimeout: 10000,
    hookTimeout: 10000,
    // 测试时不输出 INFO 级别日志，减少噪音
    silent: false,
  },
})
