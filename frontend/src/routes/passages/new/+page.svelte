<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import SegmentEditor from '$lib/components/SegmentEditor.svelte';
	import { api } from '$lib/api/client';
	import type { LanguageProfile } from '$lib/api/types';
	import { autoSegment, draftsToInputs, type DraftSegment } from '$lib/utils/segments';

	let languages: LanguageProfile[] = $state([]);
	let title = $state('');
	let description = $state('');
	let work = $state('');
	let languageProfileId = $state('');
	let sourceText = $state('');
	let drafts: DraftSegment[] = $state([]);
	let error = $state('');
	let creating = $state(false);

	const profile = $derived(languages.find((candidate) => candidate.id === languageProfileId) ?? null);

	onMount(async () => {
		languages = await api.listLanguages();
		languageProfileId = languages[0]?.id ?? '';
	});

	function generateSegments() {
		// Whitespace tokenization is wrong for unsegmented scripts; profiles
		// like Japanese declare manual_tokens in their segmentation defaults.
		const tokenize = !profile?.segmentation_defaults?.manual_tokens;
		drafts = autoSegment(sourceText, { tokenize: Boolean(tokenize) });
	}

	async function create() {
		error = '';
		creating = true;
		try {
			// A passage without segments cannot start sessions, so creating
			// straight from source text falls back to one line per line.
			const effectiveDrafts = drafts.length ? drafts : autoSegment(sourceText);
			const created = await api.createPassage({
				title: title.trim(),
				description: description.trim() || null,
				language_profile_id: languageProfileId,
				source_text: sourceText,
				hierarchy: work.trim() ? { work: work.trim() } : {},
				segments: draftsToInputs(effectiveDrafts, profile)
			});
			await goto(`/passages/${created.id}`);
		} catch (cause) {
			error = `Could not create the passage: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			creating = false;
		}
	}
</script>

<svelte:head><title>New passage · Rhapsode</title></svelte:head>

<span class="eyebrow">New passage</span>
<h1>Add a text to memorize</h1>

{#if error}<p class="error-banner" role="alert">{error}</p>{/if}

<div class="form">
	<div class="row">
		<div class="field grow">
			<label for="title">Title</label>
			<input id="title" bind:value={title} placeholder="Iliad 1.1–2" />
		</div>
		<div class="field">
			<label for="language">Language</label>
			<select id="language" bind:value={languageProfileId}>
				{#each languages as language (language.id)}
					<option value={language.id}>{language.name}</option>
				{/each}
			</select>
		</div>
	</div>

	<div class="row">
		<div class="field grow">
			<label for="description">Description</label>
			<input id="description" bind:value={description} placeholder="Opening invocation" />
		</div>
		<div class="field">
			<label for="work">Work (hierarchy)</label>
			<input id="work" bind:value={work} placeholder="Iliad" />
		</div>
	</div>

	<div class="field">
		<label for="source">Source text — one line per line of verse or prose</label>
		<textarea id="source" rows="6" bind:value={sourceText} class="passage-text"></textarea>
	</div>

	<div class="row">
		<button onclick={generateSegments} disabled={!sourceText.trim()}>
			Generate line segments
		</button>
		{#if drafts.length}
			<span class="muted">{drafts.length} line{drafts.length === 1 ? '' : 's'} — refine below, add chunks/tokens, cues, and annotations</span>
		{/if}
	</div>

	{#if drafts.length}
		<SegmentEditor bind:drafts {profile} />
	{/if}

	<div class="row actions">
		<button class="primary" onclick={create} disabled={creating || !title.trim() || !sourceText.trim() || !languageProfileId}>
			{creating ? 'Creating…' : 'Create passage'}
		</button>
		<a href="/">Cancel</a>
	</div>
</div>

<style>
	.form {
		display: flex;
		flex-direction: column;
		gap: 18px;
		max-width: 880px;
	}

	.row {
		display: flex;
		gap: 14px;
		align-items: center;
		flex-wrap: wrap;
	}

	.field {
		min-width: 220px;
	}

	.field.grow {
		flex: 1;
	}

	.actions {
		margin-top: 8px;
	}
</style>
