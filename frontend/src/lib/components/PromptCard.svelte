<script lang="ts">
	import type { LanguageProfile, PracticeItem } from '$lib/api/types';
	import type { SegmentNode } from '$lib/utils/segments';
	import SegmentText from './SegmentText.svelte';
	import { fontStack, langCode } from '$lib/utils/language';

	let {
		item,
		profile = null,
		revealed = false,
		revealText = null,
		node = null,
		layers = [],
		onReveal
	}: {
		item: PracticeItem;
		profile?: LanguageProfile | null;
		/** Parent owns reveal state. Showing the answer is neutral (Anki model):
		 *  it is the expected self-check step and never forces a grade. */
		revealed?: boolean;
		/** cue_recall/full_passage prompts omit the answer; the parent looks it
		 *  up from the revision's segments. */
		revealText?: string | null;
		/** The practised segment's subtree, so the checked answer can show its
		 *  gloss / translation / meter interlinearly (the learner is still
		 *  acquiring the vocabulary). */
		node?: SegmentNode | null;
		/** Annotation layers the learner toggled on for the flashcard. */
		layers?: string[];
		onReveal: () => void;
	} = $props();

	// Render the rich interlinear view only when there is a segment subtree and
	// at least one layer is on; otherwise plain text keeps the card calm.
	const annotated = $derived(!!node && layers.length > 0);

	// Prompt payloads are mode-shaped on the backend (see services/planning.py)
	// and intentionally open-ended for plugin modes, hence the JSON fallback.
	const prompt = $derived(item.prompt as Record<string, unknown>);
	const instruction = $derived(typeof prompt.instruction === 'string' ? prompt.instruction : '');
	const stages = $derived(Array.isArray(prompt.stages) ? (prompt.stages as string[]) : []);
	const chain = $derived(Array.isArray(prompt.chain) ? (prompt.chain as string[]) : []);
	const hint = $derived(typeof prompt.hint === 'string' ? prompt.hint : '');

	// The full target line — also the source of last-resort cues so a session
	// planned before the lead-in cue model still shows something to recall from.
	const lineText = $derived(node?.text ?? revealText ?? '');
	function firstWords(text: string, count: number): string {
		return text.split(/\s+/).filter(Boolean).slice(0, count).join(' ');
	}
	// First glyph of each word: the lightest structural scaffold — enough shape
	// to fire recall once a line is nearly solid, without handing back the words.
	function firstLetters(text: string): string {
		return text
			.split(/\s+/)
			.filter(Boolean)
			.map((word) => `${[...word][0] ?? ''}.`)
			.join(' ');
	}
	const leadIn = $derived(
		(typeof prompt.lead_in === 'string' && prompt.lead_in) ||
			firstWords(lineText, 2) ||
			(typeof prompt.cue === 'string' ? prompt.cue : '')
	);

	let showHint = $state(false);
	let showLetters = $state(false);
	$effect(() => {
		void item.id;
		showHint = false;
		showLetters = false;
	});
	const knownMode = $derived(
		['shadowing', 'progressive_fading', 'forward_chaining', 'backward_chaining', 'cue_recall', 'random_start', 'weak_link', 'full_passage'].includes(item.mode)
	);

	let stageIndex = $state(0);
	$effect(() => {
		// reset fading stage when the item changes
		void item.id;
		stageIndex = 0;
	});

	const lang = $derived(langCode(profile));
	const fonts = $derived(fontStack(profile));
</script>

<div class="prompt card">
	<div class="head">
		<span class="tag">{item.mode.replaceAll('_', ' ')}</span>
		{#if instruction}<p class="instruction">{instruction}</p>{/if}
	</div>

	{#if item.mode === 'shadowing' || item.mode === 'random_start'}
		<p class="passage-text" {lang} style:font-family={fonts}>
			{String(prompt.target_text ?? prompt.start ?? '')}
		</p>
	{:else if item.mode === 'progressive_fading' && stages.length}
		<p class="passage-text" {lang} style:font-family={fonts}>{stages[stageIndex]}</p>
		<div class="stage-controls">
			<button disabled={stageIndex === 0} onclick={() => (stageIndex -= 1)}>More support</button>
			<span class="muted">stage {stageIndex + 1}/{stages.length}</span>
			<button disabled={stageIndex >= stages.length - 1} onclick={() => (stageIndex += 1)}>
				Fade further
			</button>
		</div>
	{:else if item.mode === 'forward_chaining' || item.mode === 'backward_chaining'}
		<ol class="chain">
			{#each chain as link (link)}
				<li class="passage-text" {lang} style:font-family={fonts}>{link}</li>
			{/each}
		</ol>
	{:else if item.mode === 'cue_recall' || item.mode === 'weak_link'}
		<p class="cue-line">
			{#if leadIn}
				<span class="cue passage-text" {lang} style:font-family={fonts}>{leadIn}</span>
			{/if}
			<span class="muted">{leadIn ? '… recite aloud to the end, then check' : 'Recite this line from memory, then check'}</span>
		</p>
		{#if showLetters && lineText}
			<p class="letters passage-text" {lang} style:font-family={fonts} title="First letter of each word">
				{firstLetters(lineText)}
			</p>
		{/if}
		<div class="cue-actions">
			{#if lineText}
				<button class="hint-toggle" onclick={() => (showLetters = !showLetters)}>
					{showLetters ? 'Hide first letters' : 'Show first letters'}
				</button>
			{/if}
			{#if hint}
				{#if showHint}
					<span class="hint passage-text" {lang} style:font-family={fonts}>{hint}</span>
				{:else}
					<button class="hint-toggle" onclick={() => (showHint = true)}>Need a hint?</button>
				{/if}
			{/if}
		</div>
	{:else if item.mode === 'full_passage'}
		<p class="muted blank">Recite the full passage from memory.</p>
	{:else if !knownMode}
		<!-- Plugin practice modes render their open-ended payload verbatim. -->
		<pre class="plugin-prompt">{JSON.stringify(item.prompt, null, 2)}</pre>
	{/if}

	{#if revealed && revealText}
		{#if annotated && node}
			<div class="revealed-text annotated">
				<SegmentText {node} {profile} {layers} showRuby={false} />
			</div>
		{:else}
			<p class="passage-text revealed-text" {lang} style:font-family={fonts}>{revealText}</p>
		{/if}
	{/if}

	{#if !revealed && (item.mode === 'cue_recall' || item.mode === 'weak_link' || item.mode === 'full_passage')}
		<button class="reveal" onclick={onReveal}>Show answer to check</button>
	{/if}
</div>

<style>
	.prompt {
		display: flex;
		flex-direction: column;
		gap: 14px;
	}

	.head {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.instruction {
		margin: 0;
		color: var(--text-dim);
	}

	.stage-controls {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.chain {
		margin: 0;
		padding-inline-start: 24px;
	}

	.cue-line {
		display: flex;
		align-items: baseline;
		gap: 10px;
		margin: 0;
	}

	.cue {
		color: var(--gold);
	}

	.revealed-text {
		border-inline-start: 3px solid var(--gold);
		padding-inline-start: 12px;
	}

	.revealed-text.annotated {
		padding-block: 4px;
	}

	.cue-actions {
		display: flex;
		align-items: center;
		gap: 16px;
		flex-wrap: wrap;
	}

	.letters {
		letter-spacing: 0.12em;
		color: var(--gold);
		margin: 0;
	}

	.hint {
		color: var(--text-dim);
		font-style: italic;
		margin: 0;
	}

	.hint-toggle {
		background: none;
		border: none;
		color: var(--text-dim);
		font-size: 0.78rem;
		padding: 0;
		text-decoration: underline dotted;
		cursor: pointer;
	}

	.blank {
		font-size: 1.1rem;
		font-style: italic;
	}

	.plugin-prompt {
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 12px;
		overflow-x: auto;
		font-size: 0.8rem;
	}

	.reveal {
		align-self: flex-start;
		color: var(--gold);
		border-color: var(--gold);
	}
</style>
