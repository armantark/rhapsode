<script lang="ts">
	import type { LanguageProfile, PracticeItem } from '$lib/api/types';
	import { fontStack, langCode } from '$lib/utils/language';

	let {
		item,
		profile = null,
		revealed = false,
		revealText = null,
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
		onReveal: () => void;
	} = $props();

	// Prompt payloads are mode-shaped on the backend (see services/planning.py)
	// and intentionally open-ended for plugin modes, hence the JSON fallback.
	const prompt = $derived(item.prompt as Record<string, unknown>);
	const instruction = $derived(typeof prompt.instruction === 'string' ? prompt.instruction : '');
	const stages = $derived(Array.isArray(prompt.stages) ? (prompt.stages as string[]) : []);
	const chain = $derived(Array.isArray(prompt.chain) ? (prompt.chain as string[]) : []);
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
			<span class="cue passage-text" {lang} style:font-family={fonts}>{String(prompt.cue ?? '')}</span>
			<span class="muted">… continue from memory</span>
		</p>
	{:else if item.mode === 'full_passage'}
		<p class="muted blank">Recite the full passage from memory.</p>
	{:else if !knownMode}
		<!-- Plugin practice modes render their open-ended payload verbatim. -->
		<pre class="plugin-prompt">{JSON.stringify(item.prompt, null, 2)}</pre>
	{/if}

	{#if revealed && revealText}
		<p class="passage-text revealed-text" {lang} style:font-family={fonts}>{revealText}</p>
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
