<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import AudioPlayer from '$lib/components/AudioPlayer.svelte';
	import { api } from '$lib/api/client';
	import type { Passage, ReviewState, WeakLink } from '$lib/api/types';
	import { forgetMedia, savedBestMedia, type MediaRecord } from '$lib/utils/mediaRegistry';

	type Tab = 'due' | 'mastery' | 'weak' | 'best';
	let tab: Tab = $state('due');

	let due: ReviewState[] = $state([]);
	let allStates: ReviewState[] = $state([]);
	let weak: WeakLink[] = $state([]);
	let best: MediaRecord[] = $state([]);
	let passages: Passage[] = $state([]);
	let revisionFilter = $state('');
	let revisionTitles: Map<string, string> = $state(new Map());
	let segmentContext: Map<string, { text: string; passageId: string; revisionId: string; title: string }> = $state(new Map());
	let loading = $state(true);
	let error = $state('');
	let startingDue = $state('');

	// Far-future cutoff turns the due endpoint into a full mastery listing;
	// the contract has no dedicated review-state index (noted in the handoff).
	const MASTERY_HORIZON = '2999-01-01T00:00:00Z';

	onMount(async () => {
		try {
			[due, allStates, weak, passages] = await Promise.all([
				api.dueReviews(),
				api.dueReviews(MASTERY_HORIZON),
				api.weakLinks(),
				api.listPassages()
			]);
			best = savedBestMedia();
			const revisions = await Promise.all(
				passages
					.filter((passage) => passage.active_revision_id)
					.map((passage) => api.getRevision(passage.active_revision_id as string))
			);
			const titleByPassage = new Map(passages.map((passage) => [passage.id, passage.title]));
			revisionTitles = new Map(
				revisions.map((revision) => [revision.id, titleByPassage.get(revision.passage_id) ?? revision.id])
			);
			segmentContext = new Map(
				revisions.flatMap((revision) =>
					(revision.segments ?? []).map((segment) => [
						segment.id,
						{
							text: segment.text,
							passageId: revision.passage_id,
							revisionId: revision.id,
							title: titleByPassage.get(revision.passage_id) ?? ''
						}
					])
				)
			);
		} catch (cause) {
			error = `Could not load analytics: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			loading = false;
		}
	});

	// Due segments grouped by revision so each passage gets its own
	// one-click "drill the due stuff" session.
	const dueByRevision = $derived.by(() => {
		const groups = new Map<string, { title: string; count: number }>();
		for (const state of due) {
			const context = segmentContext.get(state.segment_id);
			if (!context) continue;
			const entry = groups.get(context.revisionId) ?? { title: context.title, count: 0 };
			entry.count += 1;
			groups.set(context.revisionId, entry);
		}
		return [...groups.entries()];
	});

	async function practiceDue(revisionId: string) {
		startingDue = revisionId;
		error = '';
		try {
			// No modes: the smart planner picks per segment; due_only narrows
			// the plan to what the scheduler says needs work now. The time
			// budget reuses the last choice made on the passage page.
			const storedMinutes = Number(localStorage.getItem('rhapsode.sessionMinutes'));
			const session = await api.createSession({
				revision_id: revisionId,
				due_only: true,
				...(storedMinutes > 0 ? { minutes: storedMinutes } : {})
			});
			await goto(`/practice/${session.id}`);
		} catch (cause) {
			error = `Could not start a due-review session: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			startingDue = '';
		}
	}

	// Groups walk the ladder in pedagogical order, not first-seen order.
	const STAGE_ORDER = ['new', 'learning', 'review', 'durable'];
	const masteryGroups = $derived.by(() => {
		const groups = new Map<string, ReviewState[]>();
		for (const state of allStates) {
			groups.set(state.mastery_stage, [...(groups.get(state.mastery_stage) ?? []), state]);
		}
		return [...groups.entries()].sort(
			(a, b) => STAGE_ORDER.indexOf(a[0]) - STAGE_ORDER.indexOf(b[0])
		);
	});

	// "3h overdue" reads faster than a raw timestamp and says what matters:
	// how far behind the schedule this item is.
	function dueLabel(dueAt: string): string {
		const minutes = (Date.now() - new Date(dueAt).getTime()) / 60_000;
		if (minutes < 1) return 'due now';
		if (minutes < 60) return `${Math.round(minutes)}m overdue`;
		if (minutes < 48 * 60) return `${Math.round(minutes / 60)}h overdue`;
		return `${Math.round(minutes / (24 * 60))}d overdue`;
	}

	let startingAllDue = $state(false);
	async function practiceAllDue() {
		startingAllDue = true;
		error = '';
		try {
			const session = await api.createSession({ due_only: true });
			await goto(`/practice/${session.id}`);
		} catch (cause) {
			error = `Could not start today's session: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			startingAllDue = false;
		}
	}
	async function applyWeakFilter() {
		weak = await api.weakLinks(revisionFilter || undefined);
	}

	async function deleteBest(mediaId: string) {
		await api.deleteMedia(mediaId);
		forgetMedia(mediaId);
		best = savedBestMedia();
	}

	function describeSegment(segmentId: string): string {
		const context = segmentContext.get(segmentId);
		return context ? `${context.text}` : segmentId;
	}

	function passageLink(segmentId: string): string | null {
		const context = segmentContext.get(segmentId);
		return context ? `/passages/${context.passageId}` : null;
	}

	const TABS: { id: Tab; label: string }[] = [
		{ id: 'due', label: 'Due reviews' },
		{ id: 'mastery', label: 'Mastery' },
		{ id: 'weak', label: 'Weak links' },
		{ id: 'best', label: 'Saved best' }
	];
</script>

<span class="eyebrow">Review</span>
<h1>The long game</h1>

<div class="tabs" role="tablist">
	{#each TABS as candidate (candidate.id)}
		<button
			role="tab"
			aria-selected={tab === candidate.id}
			class:active={tab === candidate.id}
			onclick={() => (tab = candidate.id)}
		>{candidate.label}</button>
	{/each}
</div>

{#if error}<p class="error-banner" role="alert">{error}</p>{/if}
{#if loading}
	<p class="muted">Loading…</p>
{:else if tab === 'due'}
	{#if due.length === 0}
		<p class="muted">Nothing due. Recite something for pleasure instead.</p>
	{:else}
		<div class="due-actions">
			{#if dueByRevision.length > 1}
				<button class="primary" disabled={startingAllDue || startingDue !== ''} onclick={practiceAllDue}>
					{startingAllDue ? 'Starting…' : `▶ Practice all ${due.length} due`}
				</button>
			{/if}
			{#each dueByRevision as [revisionId, group] (revisionId)}
				<button
					class="primary"
					disabled={startingDue !== '' || startingAllDue}
					onclick={() => practiceDue(revisionId)}
				>{startingDue === revisionId ? 'Starting…' : `▶ Practice ${group.count} due — ${group.title}`}</button>
			{/each}
		</div>
		<table>
			<thead><tr><th>Segment</th><th>Stage</th><th>Due</th><th>Clean / attempts</th></tr></thead>
			<tbody>
				{#each due as state (state.segment_id)}
					<tr>
						<td class="passage-text segment-cell">
							{#if passageLink(state.segment_id)}
								<a href={passageLink(state.segment_id)}>{describeSegment(state.segment_id)}</a>
							{:else}
								{describeSegment(state.segment_id)}
							{/if}
						</td>
						<td><span class="tag">{state.mastery_stage}</span></td>
						<td class="muted" title={new Date(state.due_at).toLocaleString()}>{dueLabel(state.due_at)}</td>
						<td class="muted">{state.clean_count} / {state.attempt_count}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
{:else if tab === 'mastery'}
	{#if allStates.length === 0}
		<p class="muted">No review history yet — grade some attempts first.</p>
	{:else}
		{#each masteryGroups as [stage, states] (stage)}
			<div class="card stage">
				<div class="stage-head">
					<span class="tag">{stage}</span>
					<span class="muted">{states.length} segment{states.length === 1 ? '' : 's'}</span>
				</div>
				<ul>
					{#each states as state (state.segment_id)}
						<li>
							<span class="passage-text segment-cell">{describeSegment(state.segment_id)}</span>
							<span class="muted"> — due {new Date(state.due_at).toLocaleDateString()}, {state.clean_count}/{state.attempt_count} clean</span>
						</li>
					{/each}
				</ul>
			</div>
		{/each}
	{/if}
{:else if tab === 'weak'}
	<div class="filter">
		<select bind:value={revisionFilter} onchange={applyWeakFilter} aria-label="Filter by passage">
			<option value="">All passages</option>
			{#each [...revisionTitles.entries()] as [revisionId, title] (revisionId)}
				<option value={revisionId}>{title}</option>
			{/each}
		</select>
	</div>
	{#if weak.length === 0}
		<p class="muted">No weak links — or no difficult attempts yet.</p>
	{:else}
		<table>
			<thead><tr><th>Segment</th><th>Difficulty</th><th>Hard / total</th><th>Hesitation</th></tr></thead>
			<tbody>
				{#each weak as link (link.segment_id)}
					<tr>
						<td class="passage-text segment-cell">{link.text}</td>
						<td>
							<div class="bar"><span style:width="{Math.round(link.difficulty_rate * 100)}%"></span></div>
							{Math.round(link.difficulty_rate * 100)}%
						</td>
						<td class="muted">{link.difficult_attempts} / {link.attempts}</td>
						<td class="muted">{link.mean_latency_ms != null ? `${(link.mean_latency_ms / 1000).toFixed(1)}s` : '—'}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
{:else if tab === 'best'}
	{#if best.length === 0}
		<p class="muted">No saved best attempts. In a session, record an attempt and press “★ Save as best”.</p>
	{:else}
		<div class="best-grid">
			{#each best as media (media.id)}
				<div class="card best-item">
					<span class="muted small">{media.segmentId ? describeSegment(media.segmentId) : media.name}</span>
					<AudioPlayer src={api.mediaUrl(media.id)} title={media.name} storageKey={media.id} />
					<button class="danger" onclick={() => deleteBest(media.id)}>Delete recording</button>
				</div>
			{/each}
		</div>
	{/if}
{/if}

<style>
	h1 {
		margin: 6px 0 16px;
	}

	.tabs {
		display: flex;
		gap: 8px;
		margin-bottom: 20px;
		flex-wrap: wrap;
	}

	.tabs .active {
		border-color: var(--gold);
		color: var(--gold);
		background: var(--gold-glow);
	}

	table {
		width: 100%;
		border-collapse: collapse;
	}

	th {
		text-align: start;
		font-family: var(--font-mono);
		font-size: 0.66rem;
		text-transform: uppercase;
		letter-spacing: 0.1em;
		color: var(--text-dim);
		padding: 8px 10px;
		border-bottom: 1px solid var(--border);
	}

	td {
		padding: 10px;
		border-bottom: 1px solid var(--border);
	}

	.segment-cell {
		font-size: 1.05rem;
	}

	.stage {
		margin-bottom: 14px;
	}

	.stage-head {
		display: flex;
		gap: 10px;
		align-items: center;
		margin-bottom: 8px;
	}

	.stage ul {
		margin: 0;
		padding-inline-start: 18px;
	}

	.bar {
		display: inline-block;
		width: 120px;
		height: 8px;
		background: var(--surface-2);
		border-radius: 4px;
		margin-inline-end: 8px;
		vertical-align: middle;
		overflow: hidden;
	}

	.bar span {
		display: block;
		height: 100%;
		background: linear-gradient(90deg, var(--gold), var(--red));
	}

	.filter {
		margin-bottom: 14px;
		max-width: 320px;
	}

	.due-actions {
		display: flex;
		gap: 10px;
		flex-wrap: wrap;
		margin-bottom: 16px;
	}

	.best-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
		gap: 14px;
	}

	.best-item {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.best-item .danger {
		align-self: flex-end;
		font-size: 0.72rem;
	}

	.small {
		font-size: 0.82rem;
	}
</style>
