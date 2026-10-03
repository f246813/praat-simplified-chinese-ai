import { defineConfig } from '@playwright/test';
import { join } from 'node:path';
const scratch = process.env.PI_SCRATCH_DIR;
export default defineConfig({
  testDir: './tests/browser', timeout: 45000, workers: 1,
  outputDir: scratch ? join(scratch,'frontend-playwright-results') : './test-results',
  reporter: 'list', use: {baseURL: 'http://127.0.0.1:5178', viewport: {width:1280,height:850}, screenshot:'only-on-failure', trace:'retain-on-failure'},
  webServer: {command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5178 --strictPort',url:'http://127.0.0.1:5178',reuseExistingServer:false,timeout:60000},
});
