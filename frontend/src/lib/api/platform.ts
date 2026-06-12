/** Browser dev uses the Vite proxy; Tauri asks Rust for the loopback API base. */
let apiBase = '/api/v1';

export function isTauri(): boolean {
	return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

export async function initApiBase(): Promise<string> {
	if (!isTauri()) return apiBase;
	const { invoke } = await import('@tauri-apps/api/core');
	apiBase = await invoke<string>('api_base_url');
	return apiBase;
}

export function getApiBase(): string {
	return apiBase;
}

/** Vitest-only reset so each test starts from the browser default. */
export function resetApiBaseForTests(): void {
	apiBase = '/api/v1';
}
