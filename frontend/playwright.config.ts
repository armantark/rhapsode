import { defineConfig } from '@playwright/test';

// E2e drives the real backend, but on a dedicated port and data directory so
// it never pollutes the development database.
const E2E_BACKEND = 'http://127.0.0.1:8643';
const E2E_FRONTEND_PORT = 5181;

export default defineConfig({
	testDir: './e2e',
	timeout: 60_000,
	// The suites share one backend database, so runs are serialized to keep
	// review-analytics assertions deterministic.
	workers: 1,
	use: {
		baseURL: `http://localhost:${E2E_FRONTEND_PORT}`,
		permissions: ['microphone'],
		launchOptions: {
			args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream']
		}
	},
	webServer: [
		{
			command: 'uv run rhapsode',
			cwd: '../backend',
			env: {
				RHAPSODE_PORT: '8643',
				RHAPSODE_DATA_DIR: 'data-e2e',
				RHAPSODE_DATABASE_URL: 'sqlite:///data-e2e/rhapsode.db',
				RHAPSODE_MEDIA_DIR: 'data-e2e/media',
				RHAPSODE_BACKUP_DIR: 'data-e2e/backups'
			},
			url: `${E2E_BACKEND}/api/v1/health`,
			reuseExistingServer: true,
			timeout: 90_000
		},
		{
			command: `npm run dev -- --port ${E2E_FRONTEND_PORT} --strictPort`,
			env: { RHAPSODE_API_TARGET: E2E_BACKEND },
			url: `http://localhost:${E2E_FRONTEND_PORT}`,
			reuseExistingServer: true,
			timeout: 90_000
		}
	]
});
