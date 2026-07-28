import { defineConfig } from '@playwright/test'

const viewports = [
  { suffix: '1366x768', viewport: { width: 1366, height: 768 } },
  { suffix: '1920x1080', viewport: { width: 1920, height: 1080 } },
]

export default defineConfig({
  testDir: '../FinalRelease/系统测试代码',
  outputDir: '../FinalRelease/系统测试证据/兼容性测试/artifacts',
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  reporter: [
    ['line'],
    [
      'junit',
      { outputFile: '../FinalRelease/系统测试证据/兼容性测试/playwright-junit.xml' },
    ],
    [
      'html',
      {
        outputFolder: '../FinalRelease/系统测试证据/兼容性测试/playwright-html',
        open: 'never',
      },
    ],
  ],
  use: {
    baseURL: 'http://127.0.0.1:5173',
    locale: 'zh-CN',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: 'uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning',
      cwd: '../backend',
      env: {
        DATABASE_URL: 'sqlite:///D:/tmp/tracelab-system-test/workbench.db',
        UPLOAD_ROOT: 'D:/tmp/tracelab-system-test/uploads',
      },
      url: 'http://127.0.0.1:8000/api/v1/projects',
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: 'pnpm dev',
      cwd: '.',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
  projects: [
    ...viewports.map(({ suffix, viewport }) => ({
      name: `chrome-${suffix}`,
      use: { browserName: 'chromium' as const, channel: 'chrome', viewport },
    })),
    ...viewports.map(({ suffix, viewport }) => ({
      name: `edge-${suffix}`,
      use: { browserName: 'chromium' as const, channel: 'msedge', viewport },
    })),
    ...viewports.map(({ suffix, viewport }) => ({
      name: `firefox-${suffix}`,
      use: { browserName: 'firefox' as const, viewport },
    })),
  ],
})
