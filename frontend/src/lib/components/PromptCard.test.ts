import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import PromptCard from './PromptCard.svelte';
import type { PracticeItem } from '$lib/api/types';

// Prompt payloads mirror backend/src/rhapsode/services/planning.py exactly;
// these tests pin the renderer to that contract.
function item(mode: string, prompt: Record<string, unknown>): PracticeItem {
	return {
		id: `item-${mode}`,
		session_id: 'session-1',
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
		await fireEvent.click(screen.getByRole('button', { name: /Reveal text/ }));
		expect(onReveal).toHaveBeenCalledOnce();
		await rerender({ revealed: true });
		expect(screen.getByText('μῆνιν ἄειδε θεὰ Πηληϊάδεω Ἀχιλῆος')).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: /Reveal text/ })).toBeNull();
	});

	it('full passage starts blank with a reveal escape hatch', () => {
		render(PromptCard, {
			item: item('full_passage', { instruction: 'Recite the full passage from memory.', blank: true }),
			onReveal: vi.fn()
		});
		expect(screen.getByText('Recite the full passage from memory.', { selector: '.blank' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: /Reveal text/ })).toBeInTheDocument();
	});

	it('weak link shows the cue and reveals the target', async () => {
		render(PromptCard, {
			item: item('weak_link', { instruction: 'Repair this weak link.', cue: 'destructive', target_text: 'οὐλομένην' }),
			revealed: true,
			revealText: 'οὐλομένην',
			onReveal: vi.fn()
		});
		expect(screen.getByText('destructive')).toBeInTheDocument();
		expect(screen.getByText('οὐλομένην')).toBeInTheDocument();
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
