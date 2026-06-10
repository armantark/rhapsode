import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

// The backend ships without CORS middleware, so the dev server proxies /api
// to it instead of calling cross-origin. Override the target when the backend
// runs on a non-default port: RHAPSODE_API_TARGET=http://127.0.0.1:8642
const apiTarget = process.env.RHAPSODE_API_TARGET ?? 'http://127.0.0.1:8000';

export default defineConfig({
	plugins: [
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},

			// Single-user local-first app: build to static files that can be
			// served next to the backend. SPA fallback because routes carry ids.
			adapter: adapter({ fallback: 'index.html' })
		})
	],
	server: {
		proxy: { '/api': apiTarget }
	},
	test: {
		environment: 'jsdom',
		include: ['src/**/*.test.ts'],
		setupFiles: ['./src/tests/setup.ts']
	}
});
