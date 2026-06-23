import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import PromptCard from './PromptCard.svelte';
import type { LanguageProfile, PracticeItem } from '$lib/api/types';
import type { SegmentNode } from '$lib/utils/segments';

const japaneseProfile: LanguageProfile = {
	id: 'jp',
	slug: 'japanese',
	name: 'Japanese',
	direction: 'ltr',
	fonts: [],
	annotation_schemas: [],
	segmentation_defaults: {},
	display_options: {}
};

function lineNode(text: string): SegmentNode {
	return {
		id: 'seg-1',
		revision_id: 'rev-1',
		kind: 'line',
		text,
		ordinal: 0,
		parent_id: null,
		cue: null,
		annotations: [],
		metadata_json: {},
		children: []
	};
}

function japaneseRubyNode(): SegmentNode {
	return {
		...lineNode('空こぼれ落ちたふたつの星が'),
		children: [
			{
				...lineNode('空'),
				id: 'tok-1',
				parent_id: 'seg-1',
				kind: 'token',
				annotations: [
					{ id: 'a1', segment_id: 'tok-1', layer: 'reading', value: 'そら', data: { render: 'ruby' } }
				]
			},
			{
				...lineNode('こぼれ落ちた'),
				id: 'tok-2',
				parent_id: 'seg-1',
				kind: 'token',
				annotations: [
					{
						id: 'a2',
						segment_id: 'tok-2',
						layer: 'reading',
						value: 'こぼれおちた',
						data: { render: 'ruby' }
					}
				]
			},
			{
				...lineNode('ふたつ'),
				id: 'tok-3',
				parent_id: 'seg-1',
				kind: 'token'
			},
			{
				...lineNode('の'),
				id: 'tok-4',
				parent_id: 'seg-1',
				kind: 'token'
			},
			{
				...lineNode('星'),
				id: 'tok-5',
				parent_id: 'seg-1',
				kind: 'token',
				annotations: [
					{ id: 'a5', segment_id: 'tok-5', layer: 'reading', value: 'ほし', data: { render: 'ruby' } }
				]
			},
			{
				...lineNode('が'),
				id: 'tok-6',
				parent_id: 'seg-1',
				kind: 'token'
			}
		]
	};
}

// Prompt payloads mirror backend/src/rhapsode/services/planning.py exactly;
// these tests pin the renderer to that contract.
function item(mode: string, prompt: Record<string, unknown>): PracticeItem {
	return {
		id: `item-${mode}`,
		session_id: 'session-1',
		revision_id: 'rev-1',
		segment_id: 'seg-1',
		position: 0,
		mode,
		prompt,
		completed: false
	};
}

describe('built-in mode rendering', () => {
	it('shadowing shows the target text', () => {
		render(PromptCard, {
			item: item('shadowing', { instruction: 'Listen, then shadow aloud.', target_text: 'μῆνιν ἄειδε θεὰ' }),
			onReveal: vi.fn()
		});
		expect(screen.getByText('Listen, then shadow aloud.')).toBeInTheDocument();
		expect(screen.getByText('μῆνιν ἄειδε θεὰ')).toBeInTheDocument();
	});

	it('progressive fading steps through stages in both directions', async () => {
		render(PromptCard, {
			item: item('progressive_fading', {
				instruction: 'Recite as support fades.',
				stages: ['full text here', '… text here', '… … here', '… … …']
			}),
			onReveal: vi.fn()
		});
		expect(screen.getByText('full text here')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Fade further' }));
		expect(screen.getByText('… text here')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'More support' }));
		expect(screen.getByText('full text here')).toBeInTheDocument();
	});

	it('progressive fading shows Japanese ruby on the full-support stage', async () => {
		const { container } = render(PromptCard, {
			item: item('progressive_fading', {
				instruction: 'Recite as support fades.',
				stages: ['空こぼれ落ちたふたつの星が', '…こぼれ…たふたつの星が']
			}),
			node: japaneseRubyNode(),
			profile: japaneseProfile,
			onReveal: vi.fn()
		});
		expect([...container.querySelectorAll('rt')].map((node) => node.textContent)).toEqual([
			'そら',
			'お',
			'ほし'
		]);
		await fireEvent.click(screen.getByRole('button', { name: 'Fade further' }));
		expect([...container.querySelectorAll('.fade-token-mask')].map((node) => node.textContent)).toEqual([
			'•',
			'••••••'
		]);
		expect([...container.querySelectorAll('rt')].map((node) => node.textContent)).toEqual(['ほし']);
		await fireEvent.click(screen.getByRole('button', { name: 'Fade further' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Fade further' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Fade further' }));
		expect(container.querySelector('rt')).toBeNull();
		expect(container.querySelectorAll('.fade-token-mask')).toHaveLength(6);
		expect(screen.getByText('stage 5/5')).toBeInTheDocument();
	});

	it('forward chaining lists the chain in order', () => {
		render(PromptCard, {
			item: item('forward_chaining', { instruction: 'Recite this growing chain.', chain: ['first', 'second'] }),
			onReveal: vi.fn()
		});
		const links = screen.getAllByRole('listitem');
		expect(links.map((node) => node.textContent)).toEqual(['first', 'second']);
	});

	it('cue recall hides the answer until revealed, then shows parent-supplied text', async () => {
		const onReveal = vi.fn();
		const { rerender } = render(PromptCard, {
			item: item('cue_recall', { instruction: 'Continue from the cue.', cue: 'Sing, goddess' }),
			revealText: 'μῆνιν ἄειδε θεὰ Πηληϊάδεω Ἀχιλῆος',
			onReveal
		});
		expect(screen.queryByText('μῆνιν ἄειδε θεὰ Πηληϊάδεω Ἀχιλῆος')).toBeNull();
		await fireEvent.click(screen.getByRole('button', { name: /Show answer/ }));
		expect(onReveal).toHaveBeenCalledOnce();
		await rerender({ revealed: true });
		expect(screen.getByText('μῆνιν ἄειδε θεὰ Πηληϊάδεω Ἀχιλῆος')).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: /Show answer/ })).toBeNull();
	});

	it('revealed Japanese answers show ruby even when support layers are off', () => {
		const { container } = render(PromptCard, {
			item: item('cue_recall', { instruction: 'Continue from the cue.', cue: 'ふたつの星' }),
			node: japaneseRubyNode(),
			profile: japaneseProfile,
			revealed: true,
			revealText: '空こぼれ落ちたふたつの星が',
			onReveal: vi.fn()
		});
		expect([...container.querySelectorAll('rt')].map((node) => node.textContent)).toEqual([
			'そら',
			'お',
			'ほし'
		]);
	});

	it('full passage starts blank with a reveal escape hatch', () => {
		render(PromptCard, {
			item: item('full_passage', { instruction: 'Recite the full passage from memory.', blank: true }),
			onReveal: vi.fn()
		});
		expect(screen.getByText('Recite the whole passage from memory, start to finish.', { selector: '.blank' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: /Show answer/ })).toBeInTheDocument();
	});

	it('weak link shows the verbatim lead-in, hides the hint, reveals the target', async () => {
		render(PromptCard, {
			item: item('weak_link', {
				instruction: 'This seam keeps tripping you — recite across it.',
				lead_in: 'οἰωνοῖσί τε',
				hint: 'destructive',
				target_text: 'οὐλομένην'
			}),
			revealed: true,
			revealText: 'οὐλομένην',
			onReveal: vi.fn()
		});
		// The lead-in is the positional cue; the evocative phrase is demoted to a
		// hint behind a click, not shown by default.
		expect(screen.getByText('οἰωνοῖσί τε')).toBeInTheDocument();
		expect(screen.queryByText('destructive')).toBeNull();
		expect(screen.getByRole('button', { name: /Need a hint/ })).toBeInTheDocument();
		expect(screen.getByText('οὐλομένην')).toBeInTheDocument();
	});

	it('random start is a checkable cold start: lead-in shown, full line hidden until revealed', async () => {
		const onReveal = vi.fn();
		const { rerender } = render(PromptCard, {
			item: item('random_start', {
				instruction: 'Dropped in at a random line — recite it to the end.',
				lead_in: 'πολλὰς δ᾽',
				target_text: 'πολλὰς δ᾽ ἰφθίμους ψυχὰς Ἄϊδι προΐαψεν'
			}),
			revealText: 'πολλὰς δ᾽ ἰφθίμους ψυχὰς Ἄϊδι προΐαψεν',
			onReveal
		});
		// The instruction now states the endpoint, and the full line is withheld
		// so there is something to recall.
		expect(screen.getByText('Dropped in at a random line — recite it to the end.')).toBeInTheDocument();
		expect(screen.getByText('πολλὰς δ᾽')).toBeInTheDocument();
		expect(screen.queryByText('πολλὰς δ᾽ ἰφθίμους ψυχὰς Ἄϊδι προΐαψεν')).toBeNull();
		await fireEvent.click(screen.getByRole('button', { name: /Show answer/ }));
		expect(onReveal).toHaveBeenCalledOnce();
		await rerender({ revealed: true });
		expect(screen.getByText('πολλὰς δ᾽ ἰφθίμους ψυχὰς Ἄϊδι προΐαψεν')).toBeInTheDocument();
	});

	it('falls back to the segment opening when a stale prompt has no lead-in', () => {
		// Sessions planned before the lead-in cue model store no lead_in, which
		// left the card with nothing to recall from. The node's own text rescues it.
		render(PromptCard, {
			item: item('weak_link', { instruction: 'This seam keeps tripping you — recite across it.' }),
			node: lineNode('μῆνιν ἄειδε θεὰ Πηληϊάδεω Ἀχιλῆος'),
			onReveal: vi.fn()
		});
		expect(screen.getByText('μῆνιν ἄειδε')).toBeInTheDocument();
	});

	it('shows first letters as the lightest scaffold on demand', async () => {
		render(PromptCard, {
			item: item('cue_recall', { instruction: 'Recite this line to the end.', lead_in: 'μῆνιν ἄειδε' }),
			node: lineNode('μῆνιν ἄειδε θεὰ'),
			onReveal: vi.fn()
		});
		await fireEvent.click(screen.getByRole('button', { name: /Show first letters/ }));
		expect(screen.getByText('μ. ἄ. θ.')).toBeInTheDocument();
	});
});

describe('personal notes on the cue card', () => {
	it('prefers a live personal note over the drafted-cue hint', async () => {
		render(PromptCard, {
			item: item('cue_recall', { instruction: 'Recite this line to the end.', lead_in: 'μῆνιν ἄειδε', hint: 'wrath/anger' }),
			note: 'mēnin ~ "mean" — Achilles is mean',
			onReveal: vi.fn(),
			onSaveNote: vi.fn()
		});
		await fireEvent.click(screen.getByRole('button', { name: /Need a hint/ }));
		expect(screen.getByText('mēnin ~ "mean" — Achilles is mean')).toBeInTheDocument();
		// The frozen drafted hint is suppressed in favour of the learner's note.
		expect(screen.queryByText('wrath/anger')).toBeNull();
	});

	it('offers "Add a note" even when there is no drafted hint, and saves the draft', async () => {
		const onSaveNote = vi.fn();
		render(PromptCard, {
			item: item('cue_recall', { instruction: 'Recite this line to the end.', lead_in: 'μῆνιν ἄειδε' }),
			onReveal: vi.fn(),
			onSaveNote
		});
		await fireEvent.click(screen.getByRole('button', { name: /Add a note/ }));
		await fireEvent.click(screen.getByRole('button', { name: /Add a note/ }));
		const editor = screen.getByLabelText('Personal note');
		await fireEvent.input(editor, { target: { value: 'tabouleh trick' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save note' }));
		expect(onSaveNote).toHaveBeenCalledWith('tabouleh trick');
	});
});

describe('plugin modes', () => {
	it('renders unknown prompt payloads verbatim instead of breaking', () => {
		render(PromptCard, {
			item: item('plugin.pitch_accent', { contour: [0, 1, 1], note: 'custom' }),
			onReveal: vi.fn()
		});
		expect(screen.getByText(/"contour"/)).toBeInTheDocument();
		expect(screen.getByText(/"custom"/)).toBeInTheDocument();
	});
});
