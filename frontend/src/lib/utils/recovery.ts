/**
 * Session recovery is split between the backend (current_index and per-item
 * completed flags are persisted there) and this thin localStorage pointer,
 * which only remembers *which* session was in flight so a reloaded or crashed
 * browser can offer to resume it.
 */
const ACTIVE_SESSION_KEY = 'rhapsode.activeSession.v1';

export interface ActiveSessionPointer {
	sessionId: string;
	revisionId: string;
	passageTitle: string;
	touchedAt: string;
}

function storage(): Storage | null {
	try {
		return globalThis.localStorage ?? null;
	} catch {
		return null;
	}
}

export function rememberActiveSession(pointer: Omit<ActiveSessionPointer, 'touchedAt'>): void {
	storage()?.setItem(
		ACTIVE_SESSION_KEY,
		JSON.stringify({ ...pointer, touchedAt: new Date().toISOString() })
	);
}

export function recallActiveSession(): ActiveSessionPointer | null {
	const raw = storage()?.getItem(ACTIVE_SESSION_KEY);
	if (!raw) return null;
	try {
		return JSON.parse(raw) as ActiveSessionPointer;
	} catch {
		storage()?.removeItem(ACTIVE_SESSION_KEY);
		return null;
	}
}

export function clearActiveSession(sessionId?: string): void {
	if (sessionId && recallActiveSession()?.sessionId !== sessionId) return;
	storage()?.removeItem(ACTIVE_SESSION_KEY);
}
