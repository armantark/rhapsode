import { describe, expect, it } from 'vitest';
import greekFixture from '../../../../contracts/fixtures/ancient-greek-passage.json';
import type { Segment } from '$lib/api/types';
import {
	autoSegment,
	buildSegmentTree,
	childKind,
	draftsToInputs,
	presentKinds,
	segmentsToDrafts
} from './segments';

const greekSource = greekFixture.source_text;

describe('autoSegment', () => {
	it('splits the Greek fixture into one line draft per verse', () => {
		const drafts = autoSegment(greekSource);
		expect(drafts.map((draft) => draft.text)).toEqual([
			'μῆνιν ἄειδε θεὰ Πηληϊάδεω Ἀχιλῆος',
			'οὐλομένην, ἣ μυρί᾽ Ἀχαιοῖς ἄλγε᾽ ἔθηκε'
		]);
		expect(drafts.every((draft) => draft.kind === 'line')).toBe(true);
	});

	it('tokenizes on whitespace only when asked', () => {
		const [first] = autoSegment(greekSource, { tokenize: true });
		expect(first.children.map((child) => child.text)).toEqual([
			'μῆνιν', 'ἄειδε', 'θεὰ', 'Πηληϊάδεω', 'Ἀχιλῆος'
		]);
		expect(first.children.every((child) => child.kind === 'token')).toBe(true);
		expect(autoSegment(greekSource)[0].children).toEqual([]);
	});

	it('drops blank lines', () => {
		expect(autoSegment('a\n\n  \nb')).toHaveLength(2);
	});
});

describe('draftsToInputs', () => {
	it('assigns globally increasing depth-first ordinals and parent links', () => {
		const drafts = autoSegment('alpha beta\ngamma', { tokenize: true });
		const inputs = draftsToInputs(drafts);
		expect(inputs.map((input) => input.ordinal)).toEqual([0, 1, 2, 3, 4]);
		const lineIds = inputs.filter((input) => input.kind === 'line').map((input) => input.client_id);
		const tokens = inputs.filter((input) => input.kind === 'token');
		expect(tokens.map((token) => token.parent_client_id)).toEqual([lineIds[0], lineIds[0], lineIds[1]]);
	});

	it('attaches the profile render hint so reading layers ruby-render like the fixture', () => {
		const [draft] = autoSegment('祇園精舎の鐘の声');
		draft.annotations = [
			{ layer: 'reading', value: 'ぎおんしょうじゃのかねのこえ' },
			{ layer: 'translation', value: 'The sound of the bells of Gion Shōja' }
		];
		const japaneseProfile = {
			id: 'lang-ja',
			slug: 'japanese',
			name: 'Japanese',
			direction: 'ltr',
			fonts: [],
			annotation_schemas: [
				{ layer: 'reading', label: 'Reading', render: 'ruby' },
				{ layer: 'translation', label: 'Translation' }
			],
			segmentation_defaults: {},
			display_options: {}
		};
		const [input] = draftsToInputs([draft], japaneseProfile);
		expect(input.annotations?.[0]).toEqual({
			layer: 'reading',
			value: 'ぎおんしょうじゃのかねのこえ',
			data: { render: 'ruby' }
		});
		expect(input.annotations?.[1]).toEqual({
			layer: 'translation',
			value: 'The sound of the bells of Gion Shōja'
		});
	});

	it('nulls blank cues and drops empty annotations', () => {
		const [draft] = autoSegment('solus');
		draft.cue = '  ';
		draft.annotations = [
			{ layer: 'translation', value: 'alone' },
			{ layer: '', value: 'dropped' },
			{ layer: 'gloss', value: '   ' }
		];
		const [input] = draftsToInputs([draft]);
		expect(input.cue).toBeNull();
		expect(input.annotations).toEqual([{ layer: 'translation', value: 'alone' }]);
	});
});

function fakeSegment(partial: Partial<Segment> & Pick<Segment, 'id' | 'kind' | 'ordinal' | 'text'>): Segment {
	return {
		revision_id: 'rev-1',
		parent_id: null,
		cue: null,
		metadata_json: {},
		annotations: [],
		...partial
	};
}

describe('buildSegmentTree', () => {
	it('nests children under parents and sorts by ordinal', () => {
		const flat = [
			fakeSegment({ id: 'tok-b', kind: 'token', ordinal: 2, text: 'virumque', parent_id: 'line-1' }),
			fakeSegment({ id: 'line-2', kind: 'line', ordinal: 3, text: 'second' }),
			fakeSegment({ id: 'line-1', kind: 'line', ordinal: 0, text: 'Arma virumque' }),
			fakeSegment({ id: 'tok-a', kind: 'token', ordinal: 1, text: 'Arma', parent_id: 'line-1' })
		];
		const tree = buildSegmentTree(flat);
		expect(tree.map((node) => node.id)).toEqual(['line-1', 'line-2']);
		expect(tree[0].children.map((node) => node.text)).toEqual(['Arma', 'virumque']);
	});
});

describe('segmentsToDrafts roundtrip', () => {
	it('preserves text, cues, and annotations through draft → input → read → draft', () => {
		const drafts = autoSegment(greekSource);
		drafts[0].cue = String(greekFixture.segments[0].cue);
		drafts[0].annotations = greekFixture.segments[0].annotations.map((annotation) => ({
			layer: annotation.layer,
			value: annotation.value
		}));
		const inputs = draftsToInputs(drafts);
		const reads: Segment[] = inputs.map((input, index) =>
			fakeSegment({
				id: input.client_id ?? `seg-${index}`,
				kind: input.kind,
				ordinal: input.ordinal,
				text: input.text,
				cue: input.cue ?? null,
				parent_id: input.parent_client_id ?? null,
				annotations: (input.annotations ?? []).map((annotation, annotationIndex) => ({
					id: `ann-${index}-${annotationIndex}`,
					segment_id: input.client_id ?? `seg-${index}`,
					layer: annotation.layer,
					value: annotation.value,
					data: annotation.data ?? {}
				}))
			})
		);
		const roundtripped = segmentsToDrafts(reads);
		expect(roundtripped.map((draft) => draft.text)).toEqual(drafts.map((draft) => draft.text));
		expect(roundtripped[0].cue).toBe('Sing, goddess');
		expect(roundtripped[0].annotations.map((annotation) => annotation.layer)).toEqual([
			'translation', 'grammar'
		]);
	});
});

describe('kind helpers', () => {
	it('walks the section→line→chunk→token hierarchy', () => {
		expect(childKind('section')).toBe('line');
		expect(childKind('line')).toBe('chunk');
		expect(childKind('chunk')).toBe('token');
		expect(childKind('token')).toBeNull();
	});

	it('lists present kinds in hierarchy order', () => {
		const flat = [
			fakeSegment({ id: 'a', kind: 'token', ordinal: 1, text: 't' }),
			fakeSegment({ id: 'b', kind: 'line', ordinal: 0, text: 'l' })
		];
		expect(presentKinds(flat)).toEqual(['line', 'token']);
	});
});
