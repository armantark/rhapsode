<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api/client';
	import type { Collection } from '$lib/api/types';
	import RollupBadges from '$lib/components/RollupBadges.svelte';

	let collections: Collection[] = $state([]);
	let loading = $state(true);
	let error = $state('');
	let newName = $state('');
	let creating = $state(false);

	onMount(load);

	async function load() {
		loading = true;
		try {
			collections = await api.listCollections();
		} catch (cause) {
			error = `Could not load collections: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			loading = false;
		}
	}

	async function create() {
		const name = newName.trim();
		if (!name || creating) return;
		creating = true;
		error = '';
		try {
			const collection = await api.createCollection({ name });
			collections = [...collections, collection];
			newName = '';
		} catch (cause) {
			error = `Could not create the collection: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			creating = false;
		}
	}
</script>

<header class="head">
	<div>
		<span class="eyebrow">Collections</span>
		<h1>Stacked decks</h1>
		<p class="muted">Group passages — Iliad 1.1–5 with 1.6–10 — to drill a whole arc or just one slice.</p>
	</div>
</header>

{#if error}<p class="error-banner" role="alert">{error}</p>{/if}

<form class="create card" onsubmit={(event) => { event.preventDefault(); void create(); }}>
	<input
		type="text"
		placeholder="New collection name (e.g. Iliad 1.1–10)"
		bind:value={newName}
		maxlength="200"
		aria-label="New collection name"
	/>
	<button class="primary" type="submit" disabled={creating || !newName.trim()}>
		{creating ? 'Creating…' : '+ New collection'}
	</button>
</form>

{#if loading}
	<p class="muted">Loading…</p>
{:else if collections.length === 0}
	<div class="card empty"><p>No collections yet. Create one above, then add passages to it.</p></div>
{:else}
	<div class="grid">
		{#each collections as collection (collection.id)}
			<a class="collection card" href="/collections/{collection.id}">
				<h2>{collection.name}</h2>
				<span class="muted small">{collection.members.length} passage{collection.members.length === 1 ? '' : 's'}</span>
				<RollupBadges rollup={collection.rollup} />
			</a>
		{/each}
	</div>
{/if}

<style>
	.head {
		margin-bottom: 20px;
	}

	h1 {
		margin: 6px 0 4px;
	}

	.create {
		display: flex;
		gap: 10px;
		margin-bottom: 20px;
	}

	.create input {
		flex: 1;
		margin: 0;
	}

	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: 16px;
	}

	.collection {
		color: var(--text);
		display: flex;
		flex-direction: column;
		gap: 8px;
		transition: transform 0.15s, border-color 0.15s;
	}

	.collection:hover {
		transform: translateY(-3px);
		border-color: #43516b;
		text-decoration: none;
	}

	.collection h2 {
		margin: 0;
		font-size: 1.2rem;
	}

	.small {
		font-size: 0.8rem;
	}

	.empty {
		text-align: center;
		padding: 40px;
	}
</style>
