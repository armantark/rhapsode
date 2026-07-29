import { describe, expect, it } from 'vitest';
import { ribbonSpanFor } from './ribbon';
import type { Segment } from '$lib/api/types';

const lines = [0, 1, 2].map(
	(ordinal) =>
		({
			id: `line-${ordinal}`,
			kind: 'line',
			ordinal,
			text: `line ${ordinal}`
		}) as Segment
);
const juncture = {
	id: 'seam-1',
	kind: 'juncture',
	ordinal: 1,
	text: 'line 1 opening',
	metadata_json: { juncture_after: 0 }
} as unknown as Segment;
const segments = [lines[0], juncture, lines[1], lines[2]];
const positions = new Map(lines.map((line, index) => [line.id, index + 1]));

describe('ribbonSpanFor', () => {
	it('maps a line card to its own position', () => {
		expect(
			ribbonSpanFor({ mode: 'guided_recall', segment_id: 'line-1', prompt: {} }, segments, positions)
		).toEqual({ start: 2, end: 2, seam: false });
	});

	it('marks a juncture as a seam on its landing line', () => {
		expect(
			ribbonSpanFor({ mode: 'cue_recall', segment_id: 'seam-1', prompt: {} }, segments, positions)
		).toEqual({ start: 2, end: 2, seam: true });
	});

	it('spans a chain across its chained lines', () => {
		expect(
			ribbonSpanFor(
				{
					mode: 'forward_chaining',
					segment_id: 'line-2',
					prompt: { chain_segment_ids: ['line-0', 'line-1', 'line-2'] }
				},
				segments,
				positions
			)
		).toEqual({ start: 1, end: 3, seam: false });
	});

	it('spans the whole passage for holistic cards', () => {
		expect(
			ribbonSpanFor({ mode: 'full_passage', segment_id: 'line-0', prompt: {} }, segments, positions)
		).toEqual({ start: 1, end: 3, seam: false });
	});
});
