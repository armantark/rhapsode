import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import SegmentText from './SegmentText.svelte';
import type { LanguageProfile } from '$lib/api/types';
import type { SegmentNode } from '$lib/utils/segments';

function node(partial: Partial<SegmentNode>): SegmentNode {
	return {
		id: 'seg-1',
		revision_id: 'rev-1',
		parent_id: null,
		kind: 'line',
		ordinal: 0,
		text: '',
		cue: null,
		metadata_json: {},
		annotations: [],
		children: [],
		...partial
	};
}

function profile(partial: Partial<LanguageProfile>): LanguageProfile {
	return {
		id: 'lang-1',
		slug: 'latin',
		name: 'Latin',
		direction: 'ltr',
		fonts: [],
		annotation_schemas: [],
		segmentation_defaults: {},
		display_options: {},
		...partial
	};
}

describe('Unicode rendering across the four scripts', () => {
	it('renders polytonic Greek intact with the grc language tag', () => {
		render(SegmentText, {
			node: node({ text: 'μῆνιν ἄειδε θεὰ Πηληϊάδεω Ἀχιλῆος' }),
			profile: profile({ slug: 'ancient-greek', fonts: ['GFS Didot'] })
		});
		const text = screen.getByText('μῆνιν ἄειδε θεὰ Πηληϊάδεω Ἀχιλῆος');
		expect(text).toHaveAttribute('lang', 'grc');
		expect(text.style.fontFamily).toContain('GFS Didot');
	});

	it('renders Armenian with the xcl tag', () => {
		render(SegmentText, {
			node: node({ text: 'Ճանաչել զիմաստութիւն եւ զխրատ' }),
			profile: profile({ slug: 'classical-armenian' })
		});
		expect(screen.getByText('Ճանաչել զիմաստութիւն եւ զխրատ')).toHaveAttribute('lang', 'xcl');
	});
});

describe('ruby rendering', () => {
	const japanese = node({
		text: '祇園精舎の鐘の声',
		annotations: [
			{
				id: 'ann-1',
				segment_id: 'seg-1',
				layer: 'reading',
				value: 'ぎおんしょうじゃのかねのこえ',
				data: { render: 'ruby' }
			}
		]
	});

	it('wraps the segment in <ruby> when a ruby reading exists and showRuby is on', () => {
		const { container } = render(SegmentText, {
			node: japanese,
			profile: profile({ slug: 'japanese' })
		});
		expect(container.querySelector('ruby')).not.toBeNull();
		expect([...container.querySelectorAll('rt')].map((node) => node.textContent)).toEqual([
			'ぎおんしょうじゃ',
			'かね',
			'こえ'
		]);
	});

	it('renders plain text when ruby is toggled off', () => {
		const { container } = render(SegmentText, {
			node: japanese,
			profile: profile({ slug: 'japanese' }),
			showRuby: false
		});
		expect(container.querySelector('ruby')).toBeNull();
		expect(screen.getByText('祇園精舎の鐘の声')).toBeInTheDocument();
	});

	it('renders Japanese token children as the primary ruby reading surface', () => {
		const { container } = render(SegmentText, {
			node: node({
				text: '空こぼれ落ちた星',
				children: [
					node({
						id: 'tok-1',
						parent_id: 'seg-1',
						kind: 'token',
						ordinal: 0,
						text: '空',
						annotations: [
							{ id: 'r1', segment_id: 'tok-1', layer: 'reading', value: 'そら', data: { render: 'ruby' } },
							{ id: 'g1', segment_id: 'tok-1', layer: 'gloss', value: 'sky', data: {} }
						]
					}),
					node({
						id: 'tok-2',
						parent_id: 'seg-1',
						kind: 'token',
						ordinal: 1,
						text: 'こぼれ落ちた',
						annotations: [
							{
								id: 'r2',
								segment_id: 'tok-2',
								layer: 'reading',
								value: 'こぼれおちた',
								data: { render: 'ruby' }
							},
							{ id: 'g2', segment_id: 'tok-2', layer: 'gloss', value: 'spilled down', data: {} }
						]
					}),
					node({
						id: 'tok-3',
						parent_id: 'seg-1',
						kind: 'token',
						ordinal: 2,
						text: '星',
						annotations: [
							{ id: 'r3', segment_id: 'tok-3', layer: 'reading', value: 'ほし', data: { render: 'ruby' } },
							{ id: 'g3', segment_id: 'tok-3', layer: 'gloss', value: 'star', data: {} }
						]
					})
				]
			}),
			profile: profile({ slug: 'japanese' }),
			layers: ['gloss']
		});

		expect(screen.queryByText('空こぼれ落ちた星')).toBeNull();
		expect(container.querySelectorAll('ruby')).toHaveLength(3);
		expect(container.querySelectorAll('rt')[1]?.textContent).toBe('お');
		expect(screen.getByText('spilled down')).toBeInTheDocument();
	});

	it('does not render kana-only Japanese readings as ruby', () => {
		const { container } = render(SegmentText, {
			node: node({
				text: 'ふたつの',
				kind: 'token',
				annotations: [
					{
						id: 'r1',
						segment_id: 'tok-1',
						layer: 'reading',
						value: 'ふたつの',
						data: { render: 'ruby' }
					}
				]
			}),
			profile: profile({ slug: 'japanese' })
		});
		expect(container.querySelector('ruby')).toBeNull();
		expect(screen.getByText('ふたつの')).toBeInTheDocument();
	});
});

describe('annotations and structure', () => {
	it('shows only enabled annotation layers', () => {
		const { rerender } = render(SegmentText, {
			node: node({
				text: 'Arma virumque cano',
				annotations: [
					{ id: 'a1', segment_id: 'seg-1', layer: 'translation', value: 'I sing of arms', data: {} },
					{ id: 'a2', segment_id: 'seg-1', layer: 'meter', value: 'dactylic hexameter', data: {} }
				]
			}),
			profile: profile({}),
			layers: ['translation']
		});
		expect(screen.getByText('I sing of arms')).toBeInTheDocument();
		expect(screen.queryByText('dactylic hexameter')).toBeNull();
		void rerender;
	});

	it('renders nested children with their cues when enabled', () => {
		render(SegmentText, {
			node: node({
				text: 'parent line',
				cue: 'Arma',
				children: [node({ id: 'seg-2', kind: 'token', ordinal: 1, text: 'child token' })]
			}),
			profile: profile({}),
			showCues: true
		});
		expect(screen.getByText('Arma')).toBeInTheDocument();
		expect(screen.getByText('child token')).toBeInTheDocument();
	});
});
