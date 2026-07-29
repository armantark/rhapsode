import { describe, expect, it } from 'vitest';
import { runwayStates, selectLine, selectedRange } from './runway';

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

describe('line range selection', () => {
	it('anchors on the first tap and closes on the second', () => {
		const anchored = selectLine(null, 4);
		expect(selectedRange(anchored)).toEqual({ start: 4, end: 4 });
		expect(selectedRange(selectLine(anchored, 9))).toEqual({ start: 4, end: 9 });
	});

	it('normalizes a range picked back to front', () => {
		expect(selectedRange(selectLine(selectLine(null, 9), 4))).toEqual({ start: 4, end: 9 });
	});

	it('starts a new range once one is closed', () => {
		const closed = selectLine(selectLine(null, 2), 6);
		expect(selectedRange(selectLine(closed, 11))).toEqual({ start: 11, end: 11 });
	});

	it('has no range before the first tap', () => {
		expect(selectedRange(null)).toBeNull();
	});
});
