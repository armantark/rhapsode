import type { PracticeItem, Segment } from '$lib/api/types';

/**
 * The practice ribbon makes the session's linearity visible: every card maps
 * to a span of line positions, so the learner always sees WHERE in the poem
 * the current card sits and the trail the sweep has already covered. Cards
 * are discrete; the poem is continuous — the ribbon is the bridge.
 */
export interface RibbonSpan {
	start: number;
	end: number;
	seam: boolean;
}

export function ribbonSpanFor(
	item: Pick<PracticeItem, 'mode' | 'segment_id' | 'prompt'>,
	segments: Segment[],
	linePositions: Map<string, number>
): RibbonSpan | null {
	const total = linePositions.size;
	if (item.mode === 'full_passage' || item.mode === 'recital') {
		return total ? { start: 1, end: total, seam: false } : null;
	}
	const prompt = (item.prompt ?? {}) as Record<string, unknown>;
	const chainIds = Array.isArray(prompt.chain_segment_ids)
		? (prompt.chain_segment_ids as string[])
		: null;
	if (chainIds && chainIds.length) {
		const positions = chainIds
			.map((id) => linePositions.get(id))
			.filter((position): position is number => position !== undefined);
		if (positions.length) {
			return { start: Math.min(...positions), end: Math.max(...positions), seam: false };
		}
	}
	if (!item.segment_id) return null;
	const direct = linePositions.get(item.segment_id);
	if (direct !== undefined) return { start: direct, end: direct, seam: false };
	// A juncture shares its ordinal with its landing line: mark the seam on
	// the landing position so the ribbon shows the boundary being crossed.
	const segment = segments.find((candidate) => candidate.id === item.segment_id);
	if (segment?.kind === 'juncture') {
		const landing = segments.find(
			(candidate) => candidate.kind === 'line' && candidate.ordinal === segment.ordinal
		);
		const position = landing ? linePositions.get(landing.id) : undefined;
		if (position !== undefined) return { start: position, end: position, seam: true };
	}
	return null;
}
