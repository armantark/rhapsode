import type { Segment } from '$lib/api/types';

/**
 * A "reading" annotation flagged with data.render === "ruby" covers the
 * segment it is attached to. Japanese prep can attach readings to token
 * children, while older passages can still use one whole-line reading.
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
