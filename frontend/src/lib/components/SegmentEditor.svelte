<script lang="ts">
	import SegmentEditor from './SegmentEditor.svelte';
	import type { LanguageProfile } from '$lib/api/types';
	import { childKind, makeDraft, type DraftSegment } from '$lib/utils/segments';
	import { profileLayers } from '$lib/utils/language';

	let {
		drafts = $bindable(),
		profile = null,
		depth = 0
	}: {
		drafts: DraftSegment[];
		profile?: LanguageProfile | null;
		depth?: number;
	} = $props();

	const layers = $derived(profileLayers(profile));

	function move(index: number, delta: number) {
		const target = index + delta;
		if (target < 0 || target >= drafts.length) return;
		const copy = [...drafts];
		[copy[index], copy[target]] = [copy[target], copy[index]];
		drafts = copy;
	}

	function remove(index: number) {
		drafts = drafts.toSpliced(index, 1);
	}

	function addChild(draft: DraftSegment) {
		const kind = childKind(draft.kind);
		if (kind) draft.children = [...draft.children, makeDraft(kind)];
	}

	function addSibling() {
		const kind = drafts[0]?.kind ?? 'line';
		drafts = [...drafts, makeDraft(kind)];
	}

	function addAnnotation(draft: DraftSegment) {
		draft.annotations = [...draft.annotations, { layer: layers[0]?.layer ?? 'translation', value: '' }];
	}
</script>

<div class="editor" style:margin-inline-start="{depth * 22}px">
	{#each drafts as draft, index (draft.clientId)}
		<div class="draft card">
			<div class="row head">
				<span class="tag">{draft.kind}</span>
				<span class="spacer"></span>
				<button onclick={() => move(index, -1)} disabled={index === 0} aria-label="Move {draft.kind} up">↑</button>
				<button onclick={() => move(index, 1)} disabled={index === drafts.length - 1} aria-label="Move {draft.kind} down">↓</button>
				{#if childKind(draft.kind)}
					<button onclick={() => addChild(draft)}>+ {childKind(draft.kind)}</button>
				{/if}
				<button class="danger" onclick={() => remove(index)} aria-label="Delete {draft.kind}">✕</button>
			</div>

			<div class="row fields">
				<div class="field grow">
					<label for="text-{draft.clientId}">Text</label>
					<textarea id="text-{draft.clientId}" rows="1" bind:value={draft.text}></textarea>
				</div>
				<div class="field cue">
					<label for="cue-{draft.clientId}">Cue</label>
					<input id="cue-{draft.clientId}" bind:value={draft.cue} placeholder="recall cue" />
				</div>
			</div>

			{#each draft.annotations as annotation, annotationIndex (annotationIndex)}
				<div class="row annotation">
					<input
						class="layer"
						list="layers-{draft.clientId}"
						bind:value={annotation.layer}
						aria-label="Annotation layer"
						placeholder="layer"
					/>
					<input class="grow" bind:value={annotation.value} aria-label="Annotation value" placeholder="value" />
					<button
						class="danger"
						aria-label="Remove annotation"
						onclick={() => (draft.annotations = draft.annotations.toSpliced(annotationIndex, 1))}
					>✕</button>
				</div>
			{/each}
			<datalist id="layers-{draft.clientId}">
				{#each layers as layer (layer.layer)}<option value={layer.layer}>{layer.label}</option>{/each}
			</datalist>
			<button class="add-annotation" onclick={() => addAnnotation(draft)}>+ annotation</button>

			{#if draft.children.length}
				<SegmentEditor bind:drafts={draft.children} {profile} depth={depth + 1} />
			{/if}
		</div>
	{/each}
	{#if depth === 0}
		<button onclick={addSibling}>+ add {drafts[0]?.kind ?? 'line'}</button>
	{/if}
</div>

<style>
	.editor {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.draft {
		padding: 14px;
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.row {
		display: flex;
		gap: 8px;
		align-items: center;
		flex-wrap: wrap;
	}

	.fields {
		align-items: flex-end;
	}

	.spacer {
		flex: 1;
	}

	.field.grow, .grow {
		flex: 1;
		min-width: 220px;
	}

	.field.cue {
		width: 180px;
	}

	.field label {
		margin-bottom: 2px;
	}

	textarea {
		resize: vertical;
		font-family: var(--font-passage);
		font-size: 1.05rem;
	}

	.annotation .layer {
		width: 150px;
	}

	.add-annotation {
		align-self: flex-start;
		font-size: 0.8rem;
		padding: 4px 10px;
	}
</style>
