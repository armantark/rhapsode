<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { api } from '$lib/api/client';
	import type { Collection, LanguageProfile, Passage, PracticeMode } from '$lib/api/types';
	import { PRACTICE_MODES } from '$lib/api/types';
	import RollupBadges from '$lib/components/RollupBadges.svelte';
	import { rememberActiveSession } from '$lib/utils/recovery';

	let collection: Collection | null = $state(null);
	let passages: Passage[] = $state([]);
	let languages: LanguageProfile[] = $state([]);
	let loading = $state(true);
	let error = $state('');
	let busy = $state(false);

	let renaming = $state(false);
	let nameDraft = $state('');
	let addPassageId = $state('');

	// Launcher state mirrors the passage launcher so a collection session
	// preserves the same options (modes, grain, due-only, minutes).
	const MINUTE_CHOICES = [5, 15, 30];
	let minutesChoice: number | null = $state(null);
	let chosenModes: PracticeMode[] = $state(['cue_recall']);
	let chosenKinds: string[] = $state(['line']);
	let dueOnly = $state(false);
	let startingSession = $state(false);

	const KIND_CHOICES = ['line', 'chunk', 'token', 'section'];
	const languageById = $derived(new Map(languages.map((language) => [language.id, language])));
	// Cast: svelte-check narrows the nullable $state `collection` to `never`
	// inside $derived; the runtime value is unaffected (same quirk as session).
	const memberIds = $derived(
		new Set(((collection as Collection | null)?.members ?? []).map((member) => member.passage_id))
	);
	const addable = $derived(passages.filter((passage) => !memberIds.has(passage.id)));

	onMount(load);

	async function load() {
		loading = true;
		error = '';
		try {
			[collection, passages, languages] = await Promise.all([
				api.getCollection(page.params.id ?? ''),
				api.listPassages(),
				api.listLanguages()
			]);
			nameDraft = collection.name;
		} catch (cause) {
			error = `Could not load the collection: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			loading = false;
		}
	}

	function toggle(list: string[], value: string): string[] {
		return list.includes(value) ? list.filter((entry) => entry !== value) : [...list, value];
	}

	async function run(action: () => Promise<Collection>) {
		if (busy) return;
		busy = true;
		error = '';
		try {
			collection = await action();
		} catch (cause) {
			error = `Action failed: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			busy = false;
		}
	}

	async function rename() {
		const name = nameDraft.trim();
		if (!collection || !name) return;
		await run(() => api.updateCollection(collection!.id, { name }));
		renaming = false;
	}

	async function addMember() {
		if (!collection || !addPassageId) return;
		const passageId = addPassageId;
		addPassageId = '';
		await run(() => api.addCollectionMember(collection!.id, passageId));
	}

	async function removeMember(passageId: string) {
		if (!collection) return;
		await run(() => api.removeCollectionMember(collection!.id, passageId));
	}

	async function move(passageId: string, delta: number) {
		if (!collection) return;
		const order = collection.members.map((member) => member.passage_id);
		const from = order.indexOf(passageId);
		const to = from + delta;
		if (from < 0 || to < 0 || to >= order.length) return;
		[order[from], order[to]] = [order[to], order[from]];
		await run(() => api.reorderCollectionMembers(collection!.id, order));
	}

	async function destroy() {
		if (!collection) return;
		if (!confirm(`Delete the collection “${collection.name}”? Its passages are not affected.`)) return;
		busy = true;
		try {
			await api.deleteCollection(collection.id);
			await goto('/collections');
		} catch (cause) {
			error = `Could not delete: ${cause instanceof Error ? cause.message : cause}`;
			busy = false;
		}
	}

	async function startSession(smart = false) {
		if (!collection || collection.members.length === 0) return;
		startingSession = true;
		error = '';
		try {
			const session = await api.createSession({
				collection_id: collection.id,
				due_only: dueOnly,
				...(smart
					? { ...(minutesChoice !== null ? { minutes: minutesChoice } : {}) }
					: { modes: chosenModes, segment_kinds: chosenKinds })
			});
			rememberActiveSession({
				sessionId: session.id,
				revisionId: session.revision_id ?? '',
				passageTitle: collection.name
			});
			await goto(`/practice/${session.id}`);
		} catch (cause) {
			error = `Could not start a session: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			startingSession = false;
		}
	}
</script>

{#if loading}
	<p class="muted">Loading…</p>
{:else if !collection}
	<p class="error-banner" role="alert">{error || 'Collection not found.'}</p>
{:else}
	<header class="head">
		<div>
			<span class="eyebrow"><a href="/collections">Collections</a> · {collection.members.length} passages</span>
			{#if renaming}
				<form class="rename" onsubmit={(event) => { event.preventDefault(); void rename(); }}>
					<input bind:value={nameDraft} maxlength="200" aria-label="Collection name" />
					<button class="primary" type="submit" disabled={busy || !nameDraft.trim()}>Save</button>
					<button type="button" onclick={() => { renaming = false; nameDraft = collection!.name; }}>Cancel</button>
				</form>
			{:else}
				<h1>{collection.name}</h1>
			{/if}
		</div>
		<div class="head-actions">
			<RollupBadges rollup={collection.rollup} />
			{#if !renaming}<button onclick={() => (renaming = true)}>Rename</button>{/if}
			<button class="danger" onclick={destroy} disabled={busy}>Delete</button>
		</div>
	</header>

	{#if error}<p class="error-banner" role="alert">{error}</p>{/if}

	<section class="card">
		<span class="eyebrow">Passages (practice order)</span>
		{#if collection.members.length === 0}
			<p class="muted small">No passages yet. Add one below.</p>
		{:else}
			<ol class="members">
				{#each collection.members as member, index (member.passage_id)}
					<li>
						<span class="pos">{index + 1}</span>
						<a class="title" href="/passages/{member.passage_id}">{member.passage.title}</a>
						<span class="tag">{languageById.get(member.passage.language_profile_id)?.name ?? '—'}</span>
						<div class="row-actions">
							<button onclick={() => move(member.passage_id, -1)} disabled={busy || index === 0} aria-label="Move up">↑</button>
							<button onclick={() => move(member.passage_id, 1)} disabled={busy || index === collection.members.length - 1} aria-label="Move down">↓</button>
							<button class="danger" onclick={() => removeMember(member.passage_id)} disabled={busy}>Remove</button>
						</div>
					</li>
				{/each}
			</ol>
		{/if}

		{#if addable.length}
			<div class="add">
				<select bind:value={addPassageId} aria-label="Add a passage">
					<option value="">Add a passage…</option>
					{#each addable as passage (passage.id)}
						<option value={passage.id}>{passage.title}</option>
					{/each}
				</select>
				<button onclick={addMember} disabled={busy || !addPassageId}>+ Add</button>
			</div>
		{:else if collection.members.length}
			<p class="muted small">Every passage is already in this collection.</p>
		{/if}
	</section>

	<section class="card">
		<span class="eyebrow">Practice the whole collection</span>
		<div class="choices" role="group" aria-label="Session length">
			<button class:active={minutesChoice === null} aria-pressed={minutesChoice === null} onclick={() => (minutesChoice = null)}>standard</button>
			{#each MINUTE_CHOICES as minutes (minutes)}
				<button class:active={minutesChoice === minutes} aria-pressed={minutesChoice === minutes} onclick={() => (minutesChoice = minutes)}>≈{minutes} min</button>
			{/each}
			<button class="due-toggle" class:active={dueOnly} aria-pressed={dueOnly} onclick={() => (dueOnly = !dueOnly)}>due only</button>
		</div>
		<button
			class="primary"
			disabled={startingSession || collection.members.length === 0}
			onclick={() => startSession(true)}
		>{startingSession ? 'Starting…' : '✦ Smart session'}</button>

		<details class="manual">
			<summary class="muted small">Manual: choose modes and grain</summary>
			<div class="choices" role="group" aria-label="Modes">
				{#each PRACTICE_MODES as mode (mode)}
					<button class:active={chosenModes.includes(mode)} aria-pressed={chosenModes.includes(mode)} onclick={() => (chosenModes = toggle(chosenModes, mode) as PracticeMode[])}>{mode.replaceAll('_', ' ')}</button>
				{/each}
			</div>
			<div class="choices" role="group" aria-label="Grain">
				{#each KIND_CHOICES as kind (kind)}
					<button class:active={chosenKinds.includes(kind)} aria-pressed={chosenKinds.includes(kind)} onclick={() => (chosenKinds = toggle(chosenKinds, kind))}>{kind}</button>
				{/each}
			</div>
			<button
				class="primary"
				disabled={startingSession || collection.members.length === 0 || chosenModes.length === 0 || chosenKinds.length === 0}
				onclick={() => startSession()}
			>{startingSession ? 'Starting…' : '▶ Start manual session'}</button>
		</details>
	</section>
{/if}

<style>
	.head {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 16px;
		margin-bottom: 22px;
	}

	h1 {
		margin: 6px 0 0;
	}

	.head-actions {
		display: flex;
		align-items: center;
		gap: 10px;
		flex-wrap: wrap;
	}

	.rename {
		display: flex;
		gap: 8px;
		margin-top: 6px;
	}

	.rename input {
		margin: 0;
	}

	.card {
		margin-bottom: 18px;
	}

	.members {
		list-style: none;
		margin: 10px 0 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.members li {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 10px 12px;
		border: 1px solid var(--border);
		border-radius: 8px;
	}

	.pos {
		font-family: var(--font-mono);
		color: var(--text-dim);
		min-width: 1.5em;
	}

	.title {
		flex: 1;
		color: var(--text);
		font-weight: 500;
	}

	.row-actions {
		display: flex;
		gap: 6px;
	}

	.row-actions button {
		padding: 4px 10px;
		font-size: 0.78rem;
	}

	.add {
		display: flex;
		gap: 8px;
		margin-top: 12px;
	}

	.add select {
		flex: 1;
		margin: 0;
	}

	.choices {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin: 8px 0 12px;
	}

	.choices button.active {
		border-color: var(--gold);
		color: var(--gold);
	}

	.due-toggle.active {
		border-color: var(--green);
		color: var(--green);
	}

	.manual {
		margin-top: 14px;
	}

	.manual summary {
		cursor: pointer;
	}

	.small {
		font-size: 0.8rem;
	}

	.danger {
		border-color: var(--red);
		color: var(--red);
	}
</style>
