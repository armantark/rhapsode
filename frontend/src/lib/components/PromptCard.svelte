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
		nodes = [],
		layers = [],
		note = null,
		onReveal,
		onSaveNote
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
		/** All revision segment subtrees. Japanese prompt strings are rendered
		 *  through these nodes so every kanji-bearing target surface can carry
		 *  furigana instead of falling back to raw text. */
		nodes?: SegmentNode[];
		/** Annotation layers the learner toggled on for the flashcard. */
		layers?: string[];
		/** The learner's live personal note for this segment, fetched by the
		 *  parent. It outranks the drafted cue as the hint (a self-authored
		 *  mnemonic is the strongest nudge), and stays editable. */
		note?: string | null;
		onReveal: () => void;
		/** Persists the note for the current segment; parent owns the request. */
		onSaveNote?: (text: string) => void | Promise<void>;
	} = $props();

	const japanese = $derived(profile?.slug === 'japanese');
	const readingEnabled = $derived(!japanese || layers.includes('reading'));
	const practiceRuby = $derived(japanese && !!node);
	// Render the rich interlinear view when support layers are on, or when the
	// Japanese line can carry token boundaries. The Reading layer controls ruby.
	const annotated = $derived(!!node && (layers.length > 0 || japanese));

	// Prompt payloads are mode-shaped on the backend (see services/planning.py)
	// and intentionally open-ended for plugin modes, hence the JSON fallback.
	const prompt = $derived(item.prompt as Record<string, unknown>);
	const instruction = $derived(typeof prompt.instruction === 'string' ? prompt.instruction : '');
	const stages = $derived(Array.isArray(prompt.stages) ? (prompt.stages as string[]) : []);
	const chain = $derived(Array.isArray(prompt.chain) ? (prompt.chain as string[]) : []);
	const isChaining = $derived(item.mode === 'forward_chaining' || item.mode === 'backward_chaining');
	const chainRange = $derived.by(() => {
		if (typeof prompt.range_label === 'string') return prompt.range_label;
		return chain.length === 1 ? 'line 1' : `lines 1-${chain.length}`;
	});
	const hint = $derived(typeof prompt.hint === 'string' ? prompt.hint : '');
	// A live personal note outranks the session's drafted-cue hint, which was
	// frozen at plan time. Editing the note updates the card without rebuilding
	// the session.
	const personalNote = $derived(typeof note === 'string' ? note : '');
	const effectiveHint = $derived(personalNote || hint);
	const canEditNote = $derived(!!onSaveNote && !!item.segment_id);

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
	const leadInNode = $derived.by(() => {
		if (!japanese) return null;
		if (node && node.kind !== 'juncture' && japaneseTokens.length) {
			return tokenSubsetNode(node, japaneseTokens.slice(0, 2), 'lead-in');
		}
		return leadIn ? nodeForText(leadIn) : null;
	});
	const shadowNode = $derived.by(() => {
		if (!japanese) return null;
		const text = String(prompt.target_text ?? prompt.start ?? '');
		return nodeForText(text) ?? node;
	});
	const chainDisplays = $derived.by(() =>
		chain.map((text) => ({ text, node: japanese ? nodeForText(text) : null }))
	);
	const hintNode = $derived.by(() =>
		japanese && effectiveHint ? nodeForText(effectiveHint) : null
	);
	// A juncture fading card carries the previous line's tail as a persistent
	// anchor — the association being trained is tail→head, so the transition
	// must stay identifiable even at the fully faded stage.
	const fadeLeadIn = $derived(
		item.mode === 'progressive_fading' && typeof prompt.lead_in === 'string' ? prompt.lead_in : ''
	);
	const fadeLeadInNode = $derived.by(() =>
		japanese && fadeLeadIn ? nodeForText(fadeLeadIn) : null
	);
	const fullPassageNodes = $derived.by(() =>
		japanese && item.mode === 'full_passage'
			? nodes.filter((candidate) => candidate.kind === 'line').sort((a, b) => a.ordinal - b.ordinal)
			: []
	);

	let showHint = $state(false);
	let showLetters = $state(false);
	let editingNote = $state(false);
	let noteDraft = $state('');
	let savingNote = $state(false);
	// word_bank: indices (not texts) so duplicate words stay distinct chips.
	let placedChips: number[] = $state([]);
	// typed_recall: the draft survives the reveal so the learner can eyeball
	// their attempt against the true line — the check is visual, never parsed.
	let typedDraft = $state('');
	// Guarded on the actual id (not just the item prop) so a coarse prop
	// update — e.g. the reveal flipping — can never wipe in-progress state.
	let lastItemId: string | null = null;
	$effect(() => {
		if (item.id === lastItemId) return;
		lastItemId = item.id;
		showHint = false;
		showLetters = false;
		editingNote = false;
		placedChips = [];
		typedDraft = '';
	});

	const wordBank = $derived(
		item.mode === 'word_bank' && Array.isArray(prompt.word_bank)
			? (prompt.word_bank as string[])
			: []
	);
	const poolChips = $derived(
		wordBank
			.map((text, index) => ({ text, index }))
			.filter(({ index }) => !placedChips.includes(index))
	);

	function openNoteEditor() {
		noteDraft = personalNote;
		editingNote = true;
	}

	async function saveNote() {
		if (!onSaveNote) return;
		savingNote = true;
		try {
			await onSaveNote(noteDraft.trim());
			editingNote = false;
		} finally {
			savingNote = false;
		}
	}
	const knownMode = $derived(
		['shadowing', 'progressive_fading', 'word_bank', 'forward_chaining', 'backward_chaining', 'cue_recall', 'typed_recall', 'random_start', 'weak_link', 'full_passage'].includes(item.mode)
	);

	let stageIndex = $state(0);
	$effect(() => {
		// reset fading stage when the item changes
		void item.id;
		stageIndex = 0;
	});

	const lang = $derived(langCode(profile));
	const fonts = $derived(fontStack(profile));
	const japaneseTokens = $derived(
		japanese ? tokenChildren(node) : []
	);
	const japaneseStages = $derived.by(() => {
		if (!practiceRuby || japaneseTokens.length < 2) return [];
		// Support fades from the END toward the opening: the opening is the
		// retrieval cue, so each stage asks for a longer recalled tail (mirrors
		// backend progressive_masks).
		return [0, ...hiddenCounts(japaneseTokens.length)].map((hidden) =>
			japaneseTokens.map((token, index) => ({
				token,
				hidden: index >= japaneseTokens.length - hidden,
				mask: dotMask(token.text)
			}))
		);
	});
	const stageCount = $derived(japaneseStages.length || stages.length);
	// Token children drop standalone punctuation, so a juncture head's trailing
	// continuation marker must be re-appended; it is never masked (mirrors
	// backend progressive_masks keeping ellipsis units visible).
	const fadeTrailingEllipsis = $derived(
		japaneseStages.length > 0 && (node?.text ?? '').trimEnd().endsWith('…')
	);

	function hiddenCounts(total: number): number[] {
		return [...new Set([0.25, 0.5, 0.75, 1].map((ratio) => Math.max(1, Math.round(total * ratio))))].sort(
			(a, b) => a - b
		);
	}

	function dotMask(text: string): string {
		return [...text].map((char) => (/\s/.test(char) ? char : '•')).join('');
	}

	function tokenChildren(source: SegmentNode | null): SegmentNode[] {
		return (source?.children ?? []).filter((child) => child.kind === 'token');
	}

	function normalizeText(text: string): string {
		return text.replaceAll(/[…\s]/g, '');
	}

	function nodeForText(text: string): SegmentNode | null {
		const normalized = normalizeText(text);
		if (!normalized) return null;
		for (const candidate of uniqueNodes([node, ...nodes])) {
			if (normalizeText(candidate.text) === normalized) return candidate;
			const window = tokenWindowNode(candidate, normalized);
			if (window) return window;
		}
		return null;
	}

	function uniqueNodes(candidates: Array<SegmentNode | null>): SegmentNode[] {
		const seen = new Set<string>();
		const unique: SegmentNode[] = [];
		for (const candidate of candidates) {
			if (!candidate || seen.has(candidate.id)) continue;
			seen.add(candidate.id);
			unique.push(candidate);
		}
		return unique;
	}

	function tokenWindowNode(source: SegmentNode, normalizedText: string): SegmentNode | null {
		const tokens = tokenChildren(source);
		for (let start = 0; start < tokens.length; start += 1) {
			let text = '';
			for (let end = start; end < tokens.length; end += 1) {
				text += normalizeText(tokens[end].text);
				if (text === normalizedText) {
					return tokenSubsetNode(source, tokens.slice(start, end + 1), `window-${start}-${end}`);
				}
				if (text.length >= normalizedText.length) break;
			}
		}
		return null;
	}

	function tokenSubsetNode(source: SegmentNode, tokens: SegmentNode[], suffix: string): SegmentNode | null {
		if (!tokens.length) return null;
		return {
			...source,
			id: `${source.id}-${suffix}`,
			text: tokens.map((token) => token.text).join(''),
			children: tokens
		};
	}
</script>

<div class="prompt card">
	<div class="head">
		<span class="tag">{item.mode.replaceAll('_', ' ')}</span>
		{#if instruction}<p class="instruction">{instruction}</p>{/if}
	</div>

	{#if item.mode === 'shadowing'}
		{#if shadowNode}
			<div class="passage-text rich-prompt">
				<SegmentText node={shadowNode} {profile} layers={[]} showRuby={readingEnabled} />
			</div>
		{:else}
			<p class="passage-text" {lang} style:font-family={fonts}>
				{String(prompt.target_text ?? prompt.start ?? '')}
			</p>
		{/if}
	{:else if item.mode === 'progressive_fading' && stages.length}
		{#if fadeLeadIn}
			<div class="cue-line">
				{#if fadeLeadInNode}
					<div class="cue rich-cue">
						<SegmentText node={fadeLeadInNode} {profile} layers={[]} showRuby={readingEnabled} />
					</div>
				{:else}
					<span class="cue passage-text" {lang} style:font-family={fonts}>{fadeLeadIn}</span>
				{/if}
				<span class="muted">… carry on into the next line</span>
			</div>
		{/if}
		{#if japaneseStages.length}
			<div class="passage-text rich-prompt fade-token-row">
				{#each japaneseStages[stageIndex] ?? [] as piece (piece.token.id)}
					{#if piece.hidden}
						<span class="fade-token-mask" {lang} style:font-family={fonts}>{piece.mask}</span>
					{:else}
						<SegmentText node={piece.token} {profile} layers={[]} showRuby={readingEnabled} />
					{/if}
				{/each}
				{#if fadeTrailingEllipsis}
					<span class="passage-text" {lang} style:font-family={fonts}>…</span>
				{/if}
			</div>
		{:else if practiceRuby && node && stageIndex === 0}
			<div class="passage-text rich-prompt">
				<SegmentText {node} {profile} layers={[]} showRuby={readingEnabled} />
			</div>
		{:else}
			<p class="passage-text" {lang} style:font-family={fonts}>{stages[stageIndex]}</p>
		{/if}
		<div class="stage-controls">
			<button disabled={stageIndex === 0} onclick={() => (stageIndex -= 1)}>More support</button>
			<span class="muted">stage {stageIndex + 1}/{stageCount}</span>
			<button disabled={stageIndex >= stageCount - 1} onclick={() => (stageIndex += 1)}>
				Fade further
			</button>
		</div>
	{:else if item.mode === 'word_bank' && wordBank.length}
		<div class="bank-arrangement" {lang} style:font-family={fonts}>
			{#if placedChips.length === 0}
				<span class="muted small-note">Tap the words below in recitation order — tap a placed word to take it back.</span>
			{:else}
				{#each placedChips as chipIndex (chipIndex)}
					<button
						class="chip placed"
						onclick={() => (placedChips = placedChips.filter((index) => index !== chipIndex))}
					>{wordBank[chipIndex]}</button>
				{/each}
			{/if}
		</div>
		{#if poolChips.length}
			<div class="bank-pool" {lang} style:font-family={fonts}>
				{#each poolChips as chip (chip.index)}
					<button class="chip" onclick={() => (placedChips = [...placedChips, chip.index])}>
						{chip.text}
					</button>
				{/each}
			</div>
		{/if}
	{:else if item.mode === 'typed_recall'}
		<div class="cue-line">
			{#if leadInNode}
				<div class="cue rich-cue">
					<SegmentText node={leadInNode} {profile} layers={[]} showRuby={readingEnabled} />
				</div>
			{:else if leadIn}
				<span class="cue passage-text" {lang} style:font-family={fonts}>{leadIn}</span>
			{/if}
			<span class="muted">{leadIn ? '… type from here, then check' : 'Type from memory, then check'}</span>
		</div>
		{#if revealed}
			{#if typedDraft.trim()}
				<div class="typed-attempt">
					<span class="note-tag">your attempt</span>
					<p class="passage-text" {lang} style:font-family={fonts}>{typedDraft}</p>
				</div>
			{/if}
		{:else}
			<textarea
				class="typed-input"
				bind:value={typedDraft}
				rows="2"
				{lang}
				style:font-family={fonts}
				aria-label="Type the line from memory"
				placeholder="Type from memory…"
			></textarea>
		{/if}
	{:else if isChaining}
		<p class="muted blank">Recite {chainRange} from memory.</p>
	{:else if item.mode === 'cue_recall' || item.mode === 'weak_link' || item.mode === 'random_start'}
		<div class="cue-line">
			{#if leadInNode}
				<div class="cue rich-cue">
					<SegmentText node={leadInNode} {profile} layers={[]} showRuby={readingEnabled} />
				</div>
			{:else if leadIn}
				<span class="cue passage-text" {lang} style:font-family={fonts}>{leadIn}</span>
			{/if}
			<span class="muted">{leadIn ? '… recite aloud from here, then check' : 'Recite from memory, then check'}</span>
		</div>
		{#if showLetters && lineText && !japanese}
			<p class="letters passage-text" {lang} style:font-family={fonts} title="First letter of each word">
				{firstLetters(lineText)}
			</p>
		{/if}
		<div class="cue-actions">
			{#if lineText && !japanese}
				<button class="hint-toggle" onclick={() => (showLetters = !showLetters)}>
					{showLetters ? 'Hide first letters' : 'Show first letters'}
				</button>
			{/if}
			{#if effectiveHint || canEditNote}
				{#if showHint}
					{#if effectiveHint}
						{#if hintNode}
							<div class="hint rich-hint">
								{#if personalNote}<span class="note-tag">your note</span>{/if}
								<SegmentText node={hintNode} {profile} layers={[]} showRuby={readingEnabled} />
							</div>
						{:else}
							<span class="hint passage-text" {lang} style:font-family={fonts}>
								{#if personalNote}<span class="note-tag">your note</span>{/if}{effectiveHint}
							</span>
						{/if}
					{/if}
					{#if canEditNote}
						{#if editingNote}
							<div class="note-editor">
								<textarea
									bind:value={noteDraft}
									rows="2"
									aria-label="Personal note"
									placeholder="Your own memory hook — e.g. boulē sounds like tabouleh"
								></textarea>
								<div class="note-actions">
									<button class="hint-toggle" onclick={saveNote} disabled={savingNote}>
										{savingNote ? 'Saving…' : 'Save note'}
									</button>
									<button class="hint-toggle" onclick={() => (editingNote = false)}>Cancel</button>
								</div>
							</div>
						{:else}
							<button class="hint-toggle" onclick={openNoteEditor}>
								{personalNote ? 'Edit note' : 'Add a note'}
							</button>
						{/if}
					{/if}
				{:else}
					<button class="hint-toggle" onclick={() => (showHint = true)}>
						{effectiveHint ? 'Need a hint?' : 'Add a note'}
					</button>
				{/if}
			{/if}
		</div>
	{:else if item.mode === 'full_passage'}
		<p class="muted blank">Recite the whole passage from memory, start to finish.</p>
	{:else if !knownMode}
		<!-- Plugin practice modes render their open-ended payload verbatim. -->
		<pre class="plugin-prompt">{JSON.stringify(item.prompt, null, 2)}</pre>
	{/if}

	{#if revealed && (revealText || isChaining)}
		{#if isChaining && chainDisplays.length}
			<ol class="chain revealed-text revealed-chain">
				{#each chainDisplays as link (link.text)}
					{#if link.node}
						<li class="passage-text chain-rich">
							<SegmentText node={link.node} {profile} {layers} showRuby={readingEnabled} />
						</li>
					{:else}
						<li class="passage-text" {lang} style:font-family={fonts}>{link.text}</li>
					{/if}
				{/each}
			</ol>
		{:else if annotated && node}
			<div class="revealed-text annotated">
				<SegmentText {node} {profile} {layers} showRuby={readingEnabled} />
			</div>
		{:else if fullPassageNodes.length}
			<div class="revealed-text annotated full-passage-reveal">
				{#each fullPassageNodes as line (line.id)}
					<SegmentText node={line} {profile} {layers} showRuby={readingEnabled} />
				{/each}
			</div>
		{:else}
			<p class="passage-text revealed-text" {lang} style:font-family={fonts}>{revealText}</p>
		{/if}
	{/if}

	{#if !revealed && (item.mode === 'cue_recall' || item.mode === 'weak_link' || item.mode === 'random_start' || item.mode === 'word_bank' || item.mode === 'typed_recall' || item.mode === 'full_passage' || isChaining)}
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

	.rich-prompt {
		margin: 0;
	}

	.fade-token-row {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: 10px 14px;
	}

	.fade-token-mask {
		color: var(--text-dim);
		opacity: 0.82;
	}

	.chain {
		margin: 0;
		padding-inline-start: 24px;
	}

	.chain-rich :global(.segment),
	.rich-cue :global(.segment),
	.rich-hint :global(.segment) {
		margin-bottom: 0 !important;
	}

	.cue-line {
		display: flex;
		align-items: flex-end;
		gap: 10px;
		margin: 0;
		flex-wrap: wrap;
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
		letter-spacing: 0;
		color: var(--gold);
		margin: 0;
	}

	.hint {
		color: var(--text-dim);
		font-style: italic;
		margin: 0;
	}

	.note-tag {
		font-style: normal;
		font-family: var(--font-mono);
		font-size: 0.62rem;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--gold);
		border: 1px solid var(--border);
		border-radius: 999px;
		padding: 1px 6px;
		margin-right: 8px;
		vertical-align: middle;
	}

	.note-editor {
		display: flex;
		flex-direction: column;
		gap: 6px;
		flex-basis: 100%;
	}

	.note-editor textarea {
		width: 100%;
		margin: 0;
		font-family: var(--font-ui);
		resize: vertical;
	}

	.note-actions {
		display: flex;
		gap: 12px;
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

	.bank-arrangement,
	.bank-pool {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
	}

	.bank-arrangement {
		min-height: 38px;
		border-bottom: 1px dashed var(--border);
		padding-bottom: 8px;
	}

	.chip {
		font-size: 0.95rem;
		padding: 5px 12px;
		border: 1px solid var(--gold);
		color: var(--gold);
		background: none;
		border-radius: 10px;
		cursor: pointer;
	}

	.chip.placed {
		border-color: var(--border);
		color: var(--text);
	}

	.small-note {
		font-size: 0.8rem;
	}

	.typed-input {
		width: 100%;
		font-size: 1rem;
		resize: vertical;
	}

	.typed-attempt {
		display: flex;
		align-items: baseline;
		gap: 8px;
	}

	.typed-attempt .passage-text {
		margin: 0;
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
