import { beforeEach, describe, expect, it } from 'vitest';
import { clearActiveSession, recallActiveSession, rememberActiveSession } from './recovery';

beforeEach(() => {
	localStorage.clear();
});

describe('session recovery pointer', () => {
	it('remembers and recalls the in-flight session', () => {
		rememberActiveSession({ sessionId: 's1', revisionId: 'r1', passageTitle: 'Iliad' });
		const pointer = recallActiveSession();
		expect(pointer?.sessionId).toBe('s1');
		expect(pointer?.passageTitle).toBe('Iliad');
		expect(pointer?.touchedAt).toBeTruthy();
	});

	it('only clears when the finished session matches the pointer', () => {
		rememberActiveSession({ sessionId: 's1', revisionId: 'r1', passageTitle: 'Iliad' });
		clearActiveSession('other-session');
		expect(recallActiveSession()?.sessionId).toBe('s1');
		clearActiveSession('s1');
		expect(recallActiveSession()).toBeNull();
	});

	it('drops corrupt pointers instead of crashing recovery', () => {
		localStorage.setItem('rhapsode.activeSession.v1', '{not json');
		expect(recallActiveSession()).toBeNull();
	});
});
