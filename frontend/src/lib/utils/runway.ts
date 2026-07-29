/**
 * Recitation is sequential — each line is the cue for the next — so lines
 * unlock strictly in passage order. A line is available only while it sits in
 * the active window: the first W lines that are not yet mastered. Everything
 * behind is review, everything ahead is locked and never dealt.
 *
 * The strip has to agree with the planner's gate, so the rule lives in one
 * pure place rather than inside the component. `mastered` is the planner's
 * own predicate — `acquisition_succeeded && learning_step === null` — read
 * straight from ReviewStateRead, not inferred from the derived mastery_stage.
 */

export type RunwayState = 'mastered' | 'active' | 'locked';

export function runwayStates(mastered: boolean[], windowSize: number): RunwayState[] {
	let unmastered = 0;
	return mastered.map((isMastered) => {
		if (isMastered) return 'mastered';
		unmastered += 1;
		return unmastered <= windowSize ? 'active' : 'locked';
	});
}

/**
 * Picking a line range works like a travel site's date picker: the first tap
 * anchors, the second closes the range from either direction, and a tap on a
 * closed range starts a new one. The anchor alone is already a usable
 * one-line range, so the launcher is actionable after a single tap.
 */
export interface LineSelection {
	anchor: number;
	end: number | null;
}

export interface LineRange {
	start: number;
	end: number;
}

export function selectLine(current: LineSelection | null, line: number): LineSelection {
	if (current === null || current.end !== null) return { anchor: line, end: null };
	return { anchor: current.anchor, end: line };
}

export function selectedRange(selection: LineSelection | null): LineRange | null {
	if (selection === null) return null;
	const end = selection.end ?? selection.anchor;
	return { start: Math.min(selection.anchor, end), end: Math.max(selection.anchor, end) };
}
