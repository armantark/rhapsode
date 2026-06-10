<script lang="ts">
	import SegmentText from './SegmentText.svelte';
	import type { LanguageProfile } from '$lib/api/types';
	import type { SegmentNode } from '$lib/utils/segments';
	import { rubyReading, textLayers } from '$lib/utils/ruby';
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
	const annotations = $derived(textLayers(node, layers));
	const dir = $derived(profile?.direction === 'rtl' ? 'rtl' : undefined);
	// Tokens flow horizontally as an interlinear row — a vertical word stack
	// makes a five-line passage scroll like fifty.
	const tokenChildren = $derived(node.children.filter((child) => child.kind === 'token'));
	const blockChildren = $derived(node.children.filter((child) => child.kind !== 'token'));
</script>

<div class="segment kind-{node.kind}" style:margin-inline-start="{depth * 18}px" data-segment-id={node.id}>
	<div class="body">
		{#if showCues && node.cue}
			<span class="cue" title="Recall cue">{node.cue}</span>
		{/if}
		<span class="passage-text" lang={langCode(profile)} {dir} style:font-family={fontStack(profile)}>
			{#if reading}
				<ruby>{node.text}<rt>{reading}</rt></ruby>
			{:else}
				{node.text}
			{/if}
		</span>
	</div>
	{#each annotations as annotation (annotation.layer + annotation.value)}
		<div class="annotation"><span class="tag">{annotation.layer}</span> {annotation.value}</div>
	{/each}
	{#if tokenChildren.length}
		<div class="token-row" lang={langCode(profile)} {dir}>
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
		align-items: baseline;
		gap: 2px 14px;
		margin: 4px 0 4px 18px;
	}

	/* Token chips inside the row are inline words, not stacked blocks; any
	   token-level annotations render under their word, interlinear style. */
	.token-row :global(.segment) {
		margin-bottom: 0 !important;
		margin-inline-start: 0 !important;
	}
</style>
