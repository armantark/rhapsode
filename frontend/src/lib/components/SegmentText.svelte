<script lang="ts">
	import SegmentText from './SegmentText.svelte';
	import type { LanguageProfile } from '$lib/api/types';
	import type { SegmentNode } from '$lib/utils/segments';
	import { syllableSpans, type MeterSyllable } from '$lib/utils/meter';
	import { japaneseRubyParts, rubyReading, textLayers } from '$lib/utils/ruby';
	import { fontStack, langCode } from '$lib/utils/language';

	let {
		node,
		profile = null,
		layers = [],
		showRuby = true,
		showCues = false,
		depth = 0
	}: {
		node: SegmentNode;
		profile?: LanguageProfile | null;
		layers?: string[];
		showRuby?: boolean;
		showCues?: boolean;
		depth?: number;
	} = $props();

	const reading = $derived(showRuby ? rubyReading(node) : null);
	const japaneseRuby = $derived(
		reading && profile?.slug === 'japanese' ? japaneseRubyParts(node.text, reading) : []
	);
	const dir = $derived(profile?.direction === 'rtl' ? 'rtl' : undefined);
	// Tokens flow horizontally as an interlinear row — a vertical word stack
	// makes a five-line passage scroll like fifty.
	const tokenChildren = $derived(node.children.filter((child) => child.kind === 'token'));
	const blockChildren = $derived(node.children.filter((child) => child.kind !== 'token'));
	const renderTokensAsPrimary = $derived(
		node.kind === 'line' && tokenChildren.length > 0 && profile?.slug === 'japanese'
	);
	// Quantity marks render OVER each syllable of a token (ruby) when the
	// annotation carries the syllable breakdown and it aligns to this text.
	const meterSpans = $derived.by(() => {
		if (node.kind !== 'token' || !layers.includes('meter')) return null;
		const annotation = (node.annotations ?? []).find(
			(candidate) => candidate.layer === 'meter' && Array.isArray(candidate.data?.syllables)
		);
		if (!annotation) return null;
		return syllableSpans(node.text, annotation.data?.syllables as MeterSyllable[]);
	});
	const annotations = $derived(
		textLayers(node, layers).filter(
			// Once the marks are over the syllables, the under-word fallback
			// label would say the same thing twice.
			(annotation) => !(meterSpans && annotation.layer === 'meter')
		)
	);
</script>

<div class="segment kind-{node.kind}" style:margin-inline-start="{depth * 18}px" data-segment-id={node.id}>
	<div class="body">
		{#if showCues && node.cue}
			<span class="cue" title="Recall cue">{node.cue}</span>
		{/if}
		{#if !renderTokensAsPrimary}
			<span class="passage-text" lang={langCode(profile)} {dir} style:font-family={fontStack(profile)}>
				{#if reading && profile?.slug === 'japanese'}
					{#each japaneseRuby as part, index (index)}
						{#if part.reading}
							<ruby>{part.text}<rt>{part.reading}</rt></ruby>
						{:else}
							{part.text}
						{/if}
					{/each}
				{:else if reading}
					<ruby>{node.text}<rt>{reading}</rt></ruby>
				{:else if meterSpans}
					{#each meterSpans as span, index (index)}<ruby>{span.text}<rt class="meter-mark">{span.mark}</rt></ruby>{/each}
				{:else}
					{node.text}
				{/if}
			</span>
		{/if}
	</div>
	{#each annotations as annotation (annotation.layer + annotation.value)}
		{#if node.kind === 'token'}
			<!-- Interlinear: the label sits under its word, no layer pill. -->
			<div class="annotation word-label layer-{annotation.layer}" title={annotation.layer}>
				{annotation.value}
			</div>
		{:else}
			<div class="annotation"><span class="tag">{annotation.layer}</span> {annotation.value}</div>
		{/if}
	{/each}
	{#if tokenChildren.length}
		<div class="token-row" class:primary-tokens={renderTokensAsPrimary} lang={langCode(profile)} {dir}>
			{#each tokenChildren as child (child.id)}
				<SegmentText node={child} {profile} {layers} {showRuby} {showCues} depth={0} />
			{/each}
		</div>
	{/if}
	{#each blockChildren as child (child.id)}
		<SegmentText node={child} {profile} {layers} {showRuby} {showCues} depth={depth + 1} />
	{/each}
</div>

<style>
	.segment {
		margin-bottom: 10px;
	}

	.kind-section > .body .passage-text {
		font-size: 1.6rem;
		font-weight: 600;
	}

	.kind-chunk > .body .passage-text,
	.kind-token > .body .passage-text {
		font-size: 1.05rem;
		color: var(--text-dim);
	}

	.cue {
		font-family: var(--font-mono);
		font-size: 0.7rem;
		color: var(--gold);
		border: 1px dashed var(--gold);
		border-radius: 6px;
		padding: 2px 7px;
		margin-inline-end: 10px;
		vertical-align: middle;
	}

	.annotation {
		color: var(--text-dim);
		font-size: 0.9rem;
		margin: 2px 0 2px 4px;
	}

	.token-row {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-start;
		gap: 8px 16px;
		margin: 4px 0 4px 18px;
	}

	.primary-tokens {
		gap: 10px 14px;
		margin: 2px 0 6px;
		align-items: flex-end;
	}

	/* Token chips inside the row are inline words, not stacked blocks; any
	   token-level annotations render under their word, interlinear style. */
	.token-row :global(.segment) {
		margin-bottom: 0 !important;
		margin-inline-start: 0 !important;
	}

	.primary-tokens :global(.kind-token > .body .passage-text) {
		color: var(--text);
		font-size: 1.35rem;
	}

	.word-label {
		font-size: 0.68rem;
		line-height: 1.35;
		max-width: 18ch;
		margin: 1px 0 0;
	}

	.word-label.layer-meter {
		font-family: var(--font-mono);
		color: var(--gold);
		letter-spacing: 0.08em;
	}

	.meter-mark {
		color: var(--gold);
		font-size: 0.62em;
		letter-spacing: 0;
	}
</style>
