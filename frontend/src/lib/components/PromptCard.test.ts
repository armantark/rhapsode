import { fireEvent, render, screen, within } from '@testing-library/svelte';
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
		reference_label: null,
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
			layers: ['reading'],
			onReveal: vi.fn()
		});
		expect([...container.querySelectorAll('rt')].map((node) => node.textContent)).toEqual([
			'そら',
			'お',
			'ほし'
		]);
		// Support fades from the END: the opening stays visible longest because
		// it is the retrieval cue (mirrors backend progressive_masks).
		await fireEvent.click(screen.getByRole('button', { name: 'Fade further' }));
		expect([...container.querySelectorAll('.fade-token-mask')].map((node) => node.textContent)).toEqual([
			'•',
			'•'
		]);
		expect([...container.querySelectorAll('rt')].map((node) => node.textContent)).toEqual([
			'そら',
			'お'
		]);
		await fireEvent.click(screen.getByRole('button', { name: 'Fade further' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Fade further' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Fade further' }));
		expect(container.querySelector('rt')).toBeNull();
		expect(container.querySelectorAll('.fade-token-mask')).toHaveLength(6);
		expect(screen.getByText('stage 5/5')).toBeInTheDocument();
	});

	it('acquisition sequences annotated encounter, reconstruction check, and lead-in production', async () => {
		const onReveal = vi.fn();
		const onAcquisitionReady = vi.fn();
		const acquisitionItem = item('acquisition', {
			instruction: 'Learn this line, rebuild it, then produce it from its opening.',
			target_text: '空こぼれ落ちたふたつの星が',
			word_bank: ['星', '空', 'が'],
			lead_in: '空こぼれ落ちた'
		});
		const { container, rerender } = render(PromptCard, {
			item: acquisitionItem,
			node: japaneseRubyNode(),
			profile: japaneseProfile,
			layers: ['reading'],
			revealText: '空こぼれ落ちたふたつの星が',
			onReveal,
			onAcquisitionReady
		});

		// Encounter is the full rich line, including ruby support.
		expect(screen.getByText('1 · encounter')).toHaveClass('active');
		expect(container.querySelectorAll('.acquisition-target rt').length).toBeGreaterThan(0);
		await fireEvent.click(screen.getByRole('button', { name: /I’ve read it/ }));

		// Reconstruction reuses the chip bank and checks against the true line
		// without unlocking the terminal grade/reveal yet.
		expect(screen.getByText('2 · reconstruct')).toHaveClass('active');
		expect(container.querySelector('.bank-pool')).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Show answer to check' })).toBeNull();
		while (container.querySelector('.bank-pool .chip')) {
			await fireEvent.click(container.querySelector('.bank-pool .chip') as HTMLElement);
		}
		await fireEvent.click(screen.getByRole('button', { name: 'Check reconstruction' }));
		expect(screen.getByText('true line')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: /Hide the bank/ }));

		// Production hides the bank and exposes only the deterministic lead-in
		// until the learner explicitly reveals the terminal answer.
		expect(screen.getByText('3 · produce')).toHaveClass('active');
		expect(container.querySelector('.bank-pool')).toBeNull();
		expect(screen.getByText(/recite the whole line to the end/)).toBeInTheDocument();
		expect(onAcquisitionReady).toHaveBeenLastCalledWith(true);
		await fireEvent.click(screen.getByRole('button', { name: 'Show answer to check' }));
		expect(onReveal).toHaveBeenCalledOnce();

		// A new persisted item id always restarts the internal lesson safely.
		await rerender({ item: { ...acquisitionItem, id: 'item-acquisition-retry' } });
		expect(screen.getByText('1 · encounter')).toHaveClass('active');
		expect(onAcquisitionReady).toHaveBeenLastCalledWith(false);
	});

	it('word bank deals chips that move between pool and arrangement', async () => {
		render(PromptCard, {
			item: item('word_bank', {
				instruction: 'Rebuild the line: arrange every word in order, then check.',
				word_bank: ['cano', 'arma', 'virumque'],
				target_text: 'arma virumque cano'
			}),
			onReveal: vi.fn()
		});
		// All chips start in the pool; tapping places them in recitation order.
		await fireEvent.click(screen.getByRole('button', { name: 'arma' }));
		await fireEvent.click(screen.getByRole('button', { name: 'virumque' }));
		const arrangement = document.querySelector('.bank-arrangement');
		expect(arrangement?.textContent).toContain('arma');
		expect(arrangement?.textContent).toContain('virumque');
		expect(document.querySelector('.bank-pool')?.textContent).toContain('cano');
		// Tapping a placed chip returns it to the pool.
		await fireEvent.click(within(arrangement as HTMLElement).getByRole('button', { name: 'arma' }));
		expect(document.querySelector('.bank-pool')?.textContent).toContain('arma');
		// The self-check is the standard reveal.
		expect(screen.getByRole('button', { name: /Show answer/ })).toBeInTheDocument();
	});

	it('word bank chips carry furigana over their kanji', () => {
		const { container } = render(PromptCard, {
			item: item('word_bank', {
				instruction: 'Rebuild the line: arrange every word in order, then check.',
				word_bank: ['星', '空', 'が'],
				target_text: '空こぼれ落ちたふたつの星が'
			}),
			node: japaneseRubyNode(),
			profile: japaneseProfile,
			layers: ['reading'],
			onReveal: vi.fn()
		});
		// The kanji chips (空 → そら, 星 → ほし) render ruby just like every
		// other Japanese target surface; the kana chip (が) stays plain.
		const readings = [...container.querySelectorAll('.bank-pool rt')].map((n) => n.textContent);
		expect(readings).toContain('そら');
		expect(readings).toContain('ほし');
	});

	it('typed recall keeps the attempt visible beside the revealed answer', async () => {
		const { rerender } = render(PromptCard, {
			item: item('typed_recall', {
				instruction: 'Type this line from memory to the end, then check.',
				lead_in: 'arma virumque',
				target_text: 'arma virumque cano'
			}),
			revealText: 'arma virumque cano',
			onReveal: vi.fn()
		});
		expect(screen.getByText('arma virumque')).toBeInTheDocument();
		const input = screen.getByLabelText('Type the line from memory');
		await fireEvent.input(input, { target: { value: 'arma virumque canoo' } });
		await rerender({ revealed: true });
		// The typed attempt and the true line sit stacked for a visual check —
		// nothing is parsed or diffed.
		expect(screen.getByText('arma virumque canoo')).toBeInTheDocument();
		expect(screen.getByText('arma virumque cano')).toBeInTheDocument();
		expect(screen.queryByLabelText('Type the line from memory')).toBeNull();
	});

	it('meaning recall cues from the translation and hides the original until checked', async () => {
		const { rerender } = render(PromptCard, {
			item: item('meaning_recall', {
				instruction: 'The meaning is shown — recite the original line to the end.',
				translation: 'Sing, goddess, the anger of Achilles',
				target_text: 'μῆνιν ἄειδε θεὰ'
			}),
			revealText: 'μῆνιν ἄειδε θεὰ',
			onReveal: vi.fn()
		});
		expect(screen.getByText(/Sing, goddess, the anger of Achilles/)).toBeInTheDocument();
		expect(screen.queryByText('μῆνιν ἄειδε θεὰ')).toBeNull();
		await rerender({ revealed: true });
		expect(screen.getByText('μῆνιν ἄειδε θεὰ')).toBeInTheDocument();
	});

	it('juncture recall cards with an aligned span offer the heard cue', () => {
		render(PromptCard, {
			item: item('cue_recall', {
				instruction: 'Carry on into the next line — recite just its first 2 words, then stop.',
				lead_in: '… gamma delta',
				target_text: 'epsilon zeta …',
				audio_cue: { media_id: 'media-1', start: 0, end: 4.2 }
			}),
			onReveal: vi.fn()
		});
		expect(screen.getByRole('button', { name: /Hear the cue/ })).toBeInTheDocument();
	});

	it('recital flags stumbles by number, adjusts with text, and confirms the map', async () => {
		const onRecitalConfirm = vi.fn();
		const first = { ...lineNode('Μῆνιν ἄειδε, θεά,'), id: 'line-1', ordinal: 0 };
		const second = { ...lineNode('οὐλομένην, ἣ μυρί᾽'), id: 'line-2', ordinal: 1 };
		render(PromptCard, {
			item: item('recital', {
				instruction: 'Perform the whole passage from memory, start to finish.',
				blank: true
			}),
			nodes: [second, first],
			onReveal: vi.fn(),
			onRecitalConfirm
		});
		// Performing phase: numbers only (text would make it reading, not recital).
		expect(screen.queryByText('Μῆνιν ἄειδε, θεά,')).toBeNull();
		await fireEvent.click(screen.getByRole('button', { name: '2' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Done reciting →' }));
		// Adjusting phase: texts appear, the live flag carried over.
		expect(screen.getByText('Μῆνιν ἄειδε, θεά,')).toBeInTheDocument();
		expect(screen.getByText('οὐλομένην, ἣ μυρί᾽')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Confirm recital' }));
		expect(onRecitalConfirm).toHaveBeenCalledWith(['line-2']);
	});

	it('juncture fading keeps the previous line tail visible as the anchor', () => {
		render(PromptCard, {
			item: item('progressive_fading', {
				instruction: "Recite the next line's opening as the support fades.",
				lead_in: '… ἣν ἀπηύρων',
				stages: ['τὴν δ᾽ ἐγὼ …', 'τὴν δ᾽ ••• …', '••• ••• ••• …']
			}),
			onReveal: vi.fn()
		});
		// The tail→head association is what the card trains, so the tail anchor
		// must be present at every fading stage.
		expect(screen.getByText('… ἣν ἀπηύρων')).toBeInTheDocument();
		expect(screen.getByText('τὴν δ᾽ ἐγὼ …')).toBeInTheDocument();
	});

	it('forward chaining hides the chain until the learner checks it', async () => {
		const onReveal = vi.fn();
		const { rerender } = render(PromptCard, {
			item: item('forward_chaining', {
				instruction: 'From memory, recite lines 1-2, then check.',
				chain: ['first', 'second'],
				range_label: 'lines 1-2'
			}),
			onReveal
		});
		expect(screen.getByText('Recite lines 1-2 from memory.')).toBeInTheDocument();
		expect(screen.queryByText('first')).toBeNull();
		expect(screen.queryByText('second')).toBeNull();
		await fireEvent.click(screen.getByRole('button', { name: /Show answer/ }));
		expect(onReveal).toHaveBeenCalledOnce();
		await rerender({ revealed: true });
		const links = screen.getAllByRole('listitem');
		expect(links.map((node) => node.textContent)).toEqual([
			'Line 1 of 2first',
			'Line 2 of 2second'
		]);
	});

	it('forward chaining shows canonical references instead of passage-local list numbers', () => {
		const { container } = render(PromptCard, {
			item: item('forward_chaining', {
				instruction: 'From memory, recite Iliad 1.6 through Iliad 1.7, then check.',
				chain: ['first', 'second'],
				chain_reference_labels: ['Iliad 1.6', 'Iliad 1.7'],
				range_label: 'Iliad 1.6 through Iliad 1.7'
			}),
			revealed: true,
			onReveal: vi.fn()
		});

		expect(screen.getByText('Recite Iliad 1.6 through Iliad 1.7 from memory.')).toBeInTheDocument();
		expect([...container.querySelectorAll('.chain-reference')].map((node) => node.textContent)).toEqual([
			'Iliad 1.6',
			'Iliad 1.7'
		]);
	});

	it('revealed Japanese chaining answers show ruby when reading is enabled', () => {
		const { container } = render(PromptCard, {
			item: item('forward_chaining', {
				instruction: 'From memory, recite line 1, then check.',
				chain: ['空こぼれ落ちたふたつの星が'],
				range_label: 'line 1'
			}),
			node: japaneseRubyNode(),
			nodes: [japaneseRubyNode()],
			profile: japaneseProfile,
			layers: ['reading'],
			revealed: true,
			onReveal: vi.fn()
		});
		const revealed = container.querySelector('.revealed-chain');
		expect([...revealed!.querySelectorAll('rt')].map((node) => node.textContent)).toEqual([
			'そら',
			'お',
			'ほし'
		]);
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

	it('revealed Japanese answers show ruby when the reading layer is enabled', () => {
		const { container } = render(PromptCard, {
			item: item('cue_recall', { instruction: 'Continue from the cue.', cue: 'ふたつの星' }),
			node: japaneseRubyNode(),
			profile: japaneseProfile,
			layers: ['reading'],
			revealed: true,
			revealText: '空こぼれ落ちたふたつの星が',
			onReveal: vi.fn()
		});
		const revealed = container.querySelector('.revealed-text');
		expect([...revealed!.querySelectorAll('rt')].map((node) => node.textContent)).toEqual([
			'そら',
			'お',
			'ほし'
		]);
	});

	it('hides Japanese ruby when the reading layer is toggled off', () => {
		const { container } = render(PromptCard, {
			item: item('cue_recall', { instruction: 'Continue from the cue.', cue: 'ふたつの星' }),
			node: japaneseRubyNode(),
			profile: japaneseProfile,
			revealed: true,
			revealText: '空こぼれ落ちたふたつの星が',
			onReveal: vi.fn()
		});
		expect(container.querySelector('rt')).toBeNull();
	});

	it('renders Japanese cue lead-ins with ruby and never shows the whole line as the cue', () => {
		const { container } = render(PromptCard, {
			item: item('cue_recall', {
				instruction: 'Recite this line to the end.',
				lead_in: '空こぼれ落ちたふたつの星が',
				target_text: '空こぼれ落ちたふたつの星が'
			}),
			node: japaneseRubyNode(),
			profile: japaneseProfile,
			layers: ['reading'],
			onReveal: vi.fn()
		});

		expect([...container.querySelectorAll('rt')].map((node) => node.textContent)).toEqual(['そら', 'お']);
		expect(screen.queryByText('空こぼれ落ちたふたつの星が')).toBeNull();
	});

	it('renders Japanese shadowing target text through the token ruby surface', () => {
		const { container } = render(PromptCard, {
			item: item('shadowing', {
				instruction: 'Listen, then shadow aloud.',
				target_text: '空こぼれ落ちたふたつの星が'
			}),
			node: japaneseRubyNode(),
			profile: japaneseProfile,
			layers: ['reading'],
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
