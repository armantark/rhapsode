import { describe, expect, it } from 'vitest';
import { runwayStates } from './runway';

describe('runwayStates', () => {
	it('opens a window of W lines after the mastered prefix', () => {
		expect(runwayStates([true, true, false, false, false, false], 3)).toEqual([
			'mastered',
			'mastered',
			'active',
			'active',
			'active',
			'locked'
		]);
	});

	it('locks everything past the first line at W=1', () => {
		expect(runwayStates([false, false, false], 1)).toEqual(['active', 'locked', 'locked']);
	});

	it('counts only unmastered lines against the window', () => {
		// Live data has lines mastered out of order (triage introduced them
		// before the runway existed); a mastered line must not consume a slot.
		expect(runwayStates([false, true, false, false], 2)).toEqual([
			'active',
			'mastered',
			'active',
			'locked'
		]);
	});

	it('leaves nothing locked once every line is mastered', () => {
		expect(runwayStates([true, true], 3)).toEqual(['mastered', 'mastered']);
	});
});
