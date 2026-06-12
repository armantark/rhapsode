import { afterEach, describe, expect, it, vi } from 'vitest';

const invokeMock = vi.hoisted(() => vi.fn());

vi.mock('@tauri-apps/api/core', () => ({
	invoke: invokeMock
}));

import { getApiBase, initApiBase, isTauri, resetApiBaseForTests } from './platform';

afterEach(() => {
	resetApiBaseForTests();
	invokeMock.mockReset();
	delete (globalThis as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
});

describe('api platform', () => {
	it('defaults to the Vite proxy path in the browser', () => {
		expect(isTauri()).toBe(false);
		expect(getApiBase()).toBe('/api/v1');
	});

	it('leaves the base unchanged when not running inside Tauri', async () => {
		await expect(initApiBase()).resolves.toBe('/api/v1');
		expect(invokeMock).not.toHaveBeenCalled();
	});

	it('invokes the Rust command when Tauri internals are present', async () => {
		(globalThis as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {};
		invokeMock.mockResolvedValue('http://127.0.0.1:9123/api/v1');

		await expect(initApiBase()).resolves.toBe('http://127.0.0.1:9123/api/v1');
		expect(getApiBase()).toBe('http://127.0.0.1:9123/api/v1');
		expect(invokeMock).toHaveBeenCalledWith('api_base_url');
	});
});
