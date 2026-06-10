import type { Segment } from '$lib/api/types';

/**
 * A "reading" annotation flagged with data.render === "ruby" covers the whole
 * segment. Per-character furigana alignment is a language-plugin concern on
 * the backend, so the frontend deliberately renders segment-level ruby only.
 */
export function rubyReading(segment: Pick<Segment, 'annotations'>): string | null {
	const annotation = (segment.annotations ?? []).find(
		(candidate) => candidate.layer === 'reading' && candidate.data?.render === 'ruby'
	);
	return annotation?.value ?? null;
}

/** Layers worth showing as text rows (ruby readings render inline instead). */
export function textLayers(segment: Pick<Segment, 'annotations'>, enabled: string[]): { layer: string; value: string }[] {
	return (segment.annotations ?? [])
		.filter((annotation) => enabled.includes(annotation.layer))
		.filter((annotation) => annotation.data?.render !== 'ruby')
		.map(({ layer, value }) => ({ layer, value }));
}
