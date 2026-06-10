import type { LanguageProfile, Segment, SegmentInput } from '$lib/api/types';
import { layerRenderData } from './language';

/** Hierarchy order, broadest first. A child is always one step down. */
export const SEGMENT_KINDS = ['section', 'line', 'chunk', 'token'] as const;
export type SegmentKind = (typeof SEGMENT_KINDS)[number];

export function childKind(kind: string): SegmentKind | null {
	const index = SEGMENT_KINDS.indexOf(kind as SegmentKind);
	return index >= 0 && index < SEGMENT_KINDS.length - 1 ? SEGMENT_KINDS[index + 1] : null;
}

export interface SegmentNode extends Segment {
	children: SegmentNode[];
}

/** Reassemble the flat contract list into the section/line/chunk/token tree. */
export function buildSegmentTree(segments: Segment[]): SegmentNode[] {
	const nodes = new Map<string, SegmentNode>(
		segments.map((segment) => [segment.id, { ...segment, children: [] }])
	);
	const roots: SegmentNode[] = [];
	for (const node of nodes.values()) {
		const parent = node.parent_id ? nodes.get(node.parent_id) : undefined;
		(parent ? parent.children : roots).push(node);
	}
	const byOrdinal = (a: SegmentNode, b: SegmentNode) => a.ordinal - b.ordinal;
	for (const node of nodes.values()) node.children.sort(byOrdinal);
	return roots.sort(byOrdinal);
}

export interface DraftAnnotation {
	layer: string;
	value: string;
	data?: Record<string, unknown>;
}

/** Editor-side segment: identity is a client id until the backend assigns one. */
export interface DraftSegment {
	clientId: string;
	kind: string;
	text: string;
	cue: string;
	annotations: DraftAnnotation[];
	children: DraftSegment[];
}

let draftCounter = 0;
export function newDraftId(): string {
	return `draft-${++draftCounter}-${Date.now().toString(36)}`;
}

export function makeDraft(kind: string, text = ''): DraftSegment {
	return { clientId: newDraftId(), kind, text, cue: '', annotations: [], children: [] };
}

/**
 * Split source text into line drafts; optionally tokenize on whitespace.
 * Scripts without word spacing (Japanese) keep manual tokenization.
 */
export function autoSegment(sourceText: string, options: { tokenize?: boolean } = {}): DraftSegment[] {
	return sourceText
		.split('\n')
		.map((line) => line.trim())
		.filter(Boolean)
		.map((line) => {
			const draft = makeDraft('line', line);
			if (options.tokenize) {
				draft.children = line.split(/\s+/).filter(Boolean).map((word) => makeDraft('token', word));
			}
			return draft;
		});
}

/**
 * Flatten drafts depth-first with globally increasing ordinals, which keeps
 * both the backend's global sort and its per-kind sort stable.
 */
export function draftsToInputs(
	drafts: DraftSegment[],
	profile: LanguageProfile | null = null
): SegmentInput[] {
	const inputs: SegmentInput[] = [];
	let ordinal = 0;
	const visit = (draft: DraftSegment, parentClientId: string | null) => {
		inputs.push({
			client_id: draft.clientId,
			parent_client_id: parentClientId,
			kind: draft.kind,
			ordinal: ordinal++,
			text: draft.text,
			cue: draft.cue.trim() ? draft.cue.trim() : null,
			annotations: draft.annotations
				.filter((annotation) => annotation.layer.trim() && annotation.value.trim())
				.map((annotation) => {
					const layer = annotation.layer.trim();
					const data = annotation.data ?? layerRenderData(profile, layer);
					return {
						layer,
						value: annotation.value.trim(),
						...(data ? { data } : {})
					};
				})
		});
		for (const child of draft.children) visit(child, draft.clientId);
	};
	for (const draft of drafts) visit(draft, null);
	return inputs;
}

/** Rebuild editable drafts from persisted segments (for revision forking). */
export function segmentsToDrafts(segments: Segment[]): DraftSegment[] {
	const toDraft = (node: SegmentNode): DraftSegment => ({
		clientId: node.id,
		kind: node.kind,
		text: node.text,
		cue: node.cue ?? '',
		annotations: (node.annotations ?? []).map((annotation) => ({
			layer: annotation.layer,
			value: annotation.value,
			data: Object.keys(annotation.data ?? {}).length ? annotation.data : undefined
		})),
		children: node.children.map(toDraft)
	});
	return buildSegmentTree(segments).map(toDraft);
}

/** Distinct kinds present in a revision, in hierarchy order. */
export function presentKinds(segments: Segment[]): string[] {
	const kinds = new Set(segments.map((segment) => segment.kind));
	const ordered = SEGMENT_KINDS.filter((kind) => kinds.has(kind));
	for (const kind of kinds) if (!ordered.includes(kind as SegmentKind)) ordered.push(kind as SegmentKind);
	return ordered;
}
