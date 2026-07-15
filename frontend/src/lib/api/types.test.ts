import { describe, expect, it } from 'vitest';
import { PRACTICE_MODES } from './types';

describe('manual practice modes', () => {
	it('keeps coach-only acquisition out of both manual launchers', () => {
		expect(PRACTICE_MODES).not.toContain('acquisition');
	});
});
