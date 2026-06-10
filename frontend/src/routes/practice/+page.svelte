<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api/client';
	import type { PracticeSession } from '$lib/api/types';
	import { recallActiveSession, type ActiveSessionPointer } from '$lib/utils/recovery';

	let sessions: PracticeSession[] = $state([]);
	let titles: Map<string, string> = $state(new Map());
	let pointer: ActiveSessionPointer | null = $state(null);
	let loading = $state(true);
	let error = $state('');

	onMount(async () => {
		pointer = recallActiveSession();
		try {
			sessions = await api.listSessions();
			// Sessions only carry revision ids; resolve titles via the revision's
			// passage. Parallel fetches: local backend, small N.
			const revisionIds = [...new Set(sessions.map((session) => session.revision_id))];
			const revisions = await Promise.all(revisionIds.map((id) => api.getRevision(id)));
			const passages = await api.listPassages();
			const passageTitle = new Map(passages.map((passage) => [passage.id, passage.title]));
			titles = new Map(
				revisions.map((revision) => [
					revision.id,
					passageTitle.get(revision.passage_id) ?? revision.passage_id
				])
			);
		} catch (cause) {
			error = `Could not load sessions: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			loading = false;
		}
	});

	const active = $derived(sessions.filter((session) => session.status === 'active'));
	const finished = $derived(sessions.filter((session) => session.status !== 'active'));

	function progress(session: PracticeSession): string {
		const items = session.items ?? [];
		const done = items.filter((item) => item.completed).length;
		return `${done}/${items.length}`;
	}
</script>

<span class="eyebrow">Practice</span>
<h1>Sessions</h1>

{#if error}<p class="error-banner" role="alert">{error}</p>{/if}

{#if pointer && active.some((session) => session.id === pointer?.sessionId)}
	<a class="resume-banner" href="/practice/{pointer.sessionId}">
		Resume <strong>{pointer.passageTitle}</strong> where you left off →
	</a>
{/if}

{#if loading}
	<p class="muted">Loading…</p>
{:else}
	<h2>Active</h2>
	{#if active.length === 0}
		<p class="muted">No active sessions. Start one from a passage in the <a href="/">library</a>.</p>
	{/if}
	<div class="list">
		{#each active as session (session.id)}
			<a class="card session" href="/practice/{session.id}">
				<strong>{titles.get(session.revision_id) ?? session.revision_id}</strong>
				<span class="tag">{progress(session)} items</span>
				<span class="muted">resume at #{session.current_index + 1}</span>
			</a>
		{/each}
	</div>

	{#if finished.length}
		<h2>Completed</h2>
		<div class="list">
			{#each finished as session (session.id)}
				<a class="card session completed" href="/practice/{session.id}">
					<strong>{titles.get(session.revision_id) ?? session.revision_id}</strong>
					<span class="tag">{progress(session)} items</span>
					{#if session.completed_at}
						<span class="muted">{new Date(session.completed_at).toLocaleString()}</span>
					{/if}
				</a>
			{/each}
		</div>
	{/if}
{/if}

<style>
	h1 {
		margin: 6px 0 18px;
	}

	h2 {
		font-size: 1rem;
		color: var(--text-dim);
		margin: 22px 0 10px;
	}

	.resume-banner {
		display: block;
		background: var(--gold-glow);
		border: 1px solid var(--gold);
		border-radius: 8px;
		padding: 12px 16px;
		color: var(--gold);
		margin-bottom: 12px;
	}

	.list {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.session {
		display: flex;
		align-items: center;
		gap: 14px;
		color: var(--text);
		padding: 14px 18px;
	}

	.session:hover {
		border-color: #43516b;
		text-decoration: none;
	}

	.session.completed {
		opacity: 0.7;
	}
</style>
