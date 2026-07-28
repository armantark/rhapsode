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
