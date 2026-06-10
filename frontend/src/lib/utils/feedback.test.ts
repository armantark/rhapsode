import { beforeEach, describe, expect, it } from 'vitest';
import { isSoundEnabled, setSoundEnabled } from './feedback';

describe('feedback sound preference', () => {
	beforeEach(() => localStorage.clear());

	it('defaults to enabled when nothing is stored', () => {
		expect(isSoundEnabled()).toBe(true);
	});

	it('round-trips the muted preference', () => {
		setSoundEnabled(false);
		expect(isSoundEnabled()).toBe(false);
		setSoundEnabled(true);
		expect(isSoundEnabled()).toBe(true);
	});
});
