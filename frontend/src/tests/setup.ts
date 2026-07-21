import '@testing-library/jest-dom/vitest';

// jsdom 29 removed its localStorage implementation; the app leans on it for
// practice preferences and session recovery, so tests get a faithful
// in-memory stand-in, reset between test files by jsdom teardown.
if (typeof globalThis.localStorage === 'undefined') {
	const store = new Map<string, string>();
	const storage: Storage = {
		get length() {
			return store.size;
		},
		clear: () => store.clear(),
		getItem: (key) => (store.has(key) ? (store.get(key) ?? null) : null),
		key: (index) => [...store.keys()][index] ?? null,
		removeItem: (key) => void store.delete(key),
		setItem: (key, value) => void store.set(key, String(value))
	};
	Object.defineProperty(globalThis, 'localStorage', { value: storage, configurable: true });
}
