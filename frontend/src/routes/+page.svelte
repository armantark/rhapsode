<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api/client';
	import type { LanguageProfile, Passage } from '$lib/api/types';

	let passages: Passage[] = $state([]);
	let languages: LanguageProfile[] = $state([]);
	let dueCount = $state(0);
	let loading = $state(true);
	let error = $state('');

	const languageById = $derived(new Map(languages.map((profile) => [profile.id, profile])));

	onMount(async () => {
		try {
			[passages, languages] = await Promise.all([api.listPassages(), api.listLanguages()]);
			dueCount = (await api.dueReviews()).length;
		} catch (cause) {
			error = `Could not reach the Rhapsode backend: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			loading = false;
		}
	});
</script>

<header class="head">
	<div>
		<span class="eyebrow">Passage library</span>
		<h1>Your repertoire</h1>
	</div>
	<a class="new" href="/passages/new"><button class="primary">+ New passage</button></a>
</header>

{#if error}
	<p class="error-banner" role="alert">{error}</p>
{/if}

{#if dueCount > 0}
	<a class="due-banner" href="/review">
		<strong>{dueCount}</strong> segment{dueCount === 1 ? '' : 's'} due for review →
	</a>
{/if}

{#if loading}
	<p class="muted">Loading…</p>
{:else if passages.length === 0 && !error}
	<div class="card empty">
		<p>No passages yet. Add your first text — Greek, Armenian, Latin, Japanese, or anything else.</p>
		<a href="/passages/new"><button class="primary">Create a passage</button></a>
	</div>
{:else}
	<div class="grid">
		{#each passages as passage (passage.id)}
			<a class="passage card" href="/passages/{passage.id}">
				<span class="tag">{languageById.get(passage.language_profile_id)?.name ?? 'Unknown language'}</span>
				<h2>{passage.title}</h2>
				{#if passage.description}<p class="muted">{passage.description}</p>{/if}
			</a>
		{/each}
	</div>
{/if}

<style>
	.head {
		display: flex;
		justify-content: space-between;
		align-items: flex-end;
		margin-bottom: 20px;
	}

	h1 {
		margin: 6px 0 0;
	}

	.due-banner {
		display: block;
		background: var(--gold-glow);
		border: 1px solid var(--gold);
		border-radius: 8px;
		padding: 12px 16px;
		color: var(--gold);
		margin-bottom: 20px;
	}

	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: 16px;
	}

	.passage {
		color: var(--text);
		display: flex;
		flex-direction: column;
		gap: 8px;
		transition: transform 0.15s, border-color 0.15s;
	}

	.passage:hover {
		transform: translateY(-3px);
		border-color: #43516b;
		text-decoration: none;
	}

	.passage h2 {
		margin: 0;
		font-size: 1.25rem;
	}

	.empty {
		text-align: center;
		padding: 48px;
	}

	.tag {
		align-self: flex-start;
	}
</style>
