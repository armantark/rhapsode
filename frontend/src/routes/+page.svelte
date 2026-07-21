<script lang="ts">
	import Skeleton from '$lib/components/Skeleton.svelte';
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api } from '$lib/api/client';
	import { isTauri } from '$lib/api/platform';
	import type { LanguageProfile, LibraryPassageStats, Passage, Today } from '$lib/api/types';

	let passages: Passage[] = $state([]);
	let languages: LanguageProfile[] = $state([]);
	let today: Today | null = $state(null);
	let statsByPassage: Map<string, LibraryPassageStats> = $state(new Map());
	let loading = $state(true);
	let launching = $state(false);
	let error = $state('');

	const languageById = $derived(new Map(languages.map((profile) => [profile.id, profile])));
	// The cast works around the svelte-check flow-analysis quirk (also noted in
	// the practice page) where a $state-backed nullable is narrowed to `never`
	// inside a $derived; runtime behavior is unaffected.
	const forecastMax = $derived.by(() => {
		const stats = today as Today | null;
		return stats ? Math.max(1, ...stats.forecast.map((day) => day.due)) : 1;
	});

	onMount(async () => {
		try {
			const [loadedPassages, loadedLanguages, loadedToday, stats] = await Promise.all([
				api.listPassages(),
				api.listLanguages(),
				api.today(),
				api.libraryStats()
			]);
			passages = loadedPassages;
			languages = loadedLanguages;
			today = loadedToday;
			statsByPassage = new Map(stats.map((entry) => [entry.passage_id, entry]));
			// The desktop dock icon does the daily pulling: badge = due count.
			if (isTauri()) {
				const { invoke } = await import('@tauri-apps/api/core');
				void invoke('set_due_badge', { count: today?.due_count ?? 0 }).catch(() => {});
			}
		} catch (cause) {
			error = `Could not reach the Rhapsode backend: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			loading = false;
		}
	});

	// First-run: a ready-made passage so the first five minutes teach the
	// practice loop instead of demanding data entry. Plain create through the
	// normal API — nothing special about it once it exists.
	const SAMPLE_LINES = [
		'Μῆνιν ἄειδε, θεὰ̄, Πηληϊάδεω Ἀχιλῆος',
		'οὐλομένην, ἣ μῡρί᾽ Ἀχαιοῖς ἄλγε᾽ ἔθηκε,',
		'πολλὰ̄ς δ᾽ ἰφθί̄μους ψῡχὰ̄ς Ἄϊδι προΐαψεν',
		'ἡρώων, αὐτοὺς δὲ ἑλώρια τεῦχε κύνεσσιν',
		'οἰωνοῖσί τε πᾶσι· Διὸς δ᾽ ἐτελείετο βουλή.'
	];
	let creatingSample = $state(false);

	async function createSample() {
		const greek = languages.find((profile) => profile.slug === 'ancient-greek');
		if (!greek) {
			error = 'The Ancient Greek language profile is missing; create a passage manually.';
			return;
		}
		creatingSample = true;
		error = '';
		try {
			const created = await api.createPassage({
				title: 'Sample: Iliad 1.1–5',
				language_profile_id: greek.id,
				description: 'The opening invocation — try a smart session on it.',
				source_text: SAMPLE_LINES.join('\n'),
				segments: SAMPLE_LINES.map((text, index) => ({
					client_id: `sample-line-${index + 1}`,
					kind: 'line',
					ordinal: index,
					text
				}))
			});
			await goto(`/passages/${created.id}`);
		} catch (cause) {
			error = `Could not create the sample: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			creatingSample = false;
		}
	}

	// One button, whole library, exactly what FSRS says is due — the daily
	// front door.
	async function practiceToday() {
		launching = true;
		error = '';
		try {
			const session = await api.createSession({ due_only: true });
			await goto(`/practice/${session.id}`);
		} catch (cause) {
			error = `Could not start today's session: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			launching = false;
		}
	}
</script>

<svelte:head><title>Library · Rhapsode</title></svelte:head>

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

{#if today}
	<div class="today-banner" class:clear={today.due_count === 0}>
		<div class="today-main">
			{#if today.due_count > 0}
				<span class="today-count">
					<strong>{today.due_count}</strong> due · ≈{today.estimated_minutes} min
				</span>
			{:else}
				<span class="today-count muted">Nothing due — the queue is clear. 🏛</span>
			{/if}
			{#if today.streak_days >= 2}
				<span class="today-chip" title="Consecutive days practiced">🔥 {today.streak_days}-day streak</span>
			{/if}
			{#if today.measured_retention !== null && today.retention_sample >= 20}
				<span
					class="today-chip"
					title="Recall rate over your last {today.retention_sample} reviews vs the FSRS target"
				>
					recall {Math.round(today.measured_retention * 100)}% · target {Math.round(today.desired_retention * 100)}%
				</span>
			{/if}
			<a class="today-review" href="/review">review →</a>
		</div>
		{#if today.due_count > 0}
			<button class="primary" onclick={practiceToday} disabled={launching}>
				{launching ? 'Building…' : "▶ Practice today's due"}
			</button>
		{/if}
	</div>
	{#if today.forecast.some((day) => day.due > 0)}
		<div class="forecast" title="Due segments over the next 7 days (today includes the backlog)">
			{#each today.forecast as day (day.date)}
				<div class="forecast-day">
					<div class="forecast-bar" style:height="{(day.due / forecastMax) * 34 + 2}px"></div>
					<span class="forecast-count">{day.due}</span>
				</div>
			{/each}
		</div>
	{/if}
{/if}

{#if loading}
	<Skeleton rows={4} card />
{:else if passages.length === 0 && !error}
	<div class="card empty">
		<p>No passages yet. Add your first text — Greek, Armenian, Latin, Japanese, or anything else.</p>
		<div class="empty-actions">
			<a href="/passages/new"><button class="primary">Create a passage</button></a>
			<button onclick={createSample} disabled={creatingSample}>
				{creatingSample ? 'Creating…' : 'Try a sample — Iliad 1.1–5'}
			</button>
		</div>
	</div>
{:else}
	<div class="grid">
		{#each passages as passage (passage.id)}
			{@const stats = statsByPassage.get(passage.id)}
			<a class="passage card" href="/passages/{passage.id}">
				<span class="tag">{languageById.get(passage.language_profile_id)?.name ?? 'Unknown language'}</span>
				<h2>{passage.title}</h2>
				{#if passage.description}<p class="muted">{passage.description}</p>{/if}
				{#if stats}
					<div class="stat-chips">
						{#if !stats.started}
							<span class="stat-chip">not started</span>
						{:else}
							{#if stats.due > 0}
								<span class="stat-chip due">{stats.due} due</span>
							{/if}
							<span class="stat-chip">{stats.durable}/{stats.total_units} durable</span>
							{#if stats.learning > 0}
								<span class="stat-chip">{stats.learning} learning</span>
							{/if}
						{/if}
					</div>
				{/if}
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

	.today-banner {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 14px;
		flex-wrap: wrap;
		background: var(--gold-glow);
		border: 1px solid var(--gold);
		border-radius: 8px;
		padding: 12px 16px;
		margin-bottom: 8px;
	}

	.today-banner.clear {
		background: var(--surface);
		border-color: var(--border);
	}

	.today-main {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
	}

	.today-count {
		color: var(--gold);
	}

	.today-banner.clear .today-count {
		color: var(--text-dim);
	}

	.today-chip {
		font-family: var(--font-mono);
		font-size: 0.72rem;
		color: var(--text-dim);
		border: 1px solid var(--border);
		border-radius: 999px;
		padding: 2px 9px;
	}

	.today-review {
		font-size: 0.8rem;
		color: var(--text-dim);
	}

	.forecast {
		display: flex;
		align-items: flex-end;
		gap: 6px;
		margin-bottom: 20px;
		padding: 0 4px;
	}

	.forecast-day {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 2px;
		width: 26px;
	}

	.forecast-bar {
		width: 100%;
		background: var(--surface-2, #1e232c);
		border: 1px solid var(--border);
		border-radius: 3px 3px 0 0;
	}

	.forecast-day:first-child .forecast-bar {
		background: var(--gold-glow);
		border-color: var(--gold);
	}

	.forecast-count {
		font-family: var(--font-mono);
		font-size: 0.62rem;
		color: var(--text-dim);
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

	.stat-chips {
		display: flex;
		gap: 6px;
		flex-wrap: wrap;
		margin-top: auto;
		padding-top: 6px;
	}

	.stat-chip {
		font-family: var(--font-mono);
		font-size: 0.66rem;
		color: var(--text-dim);
		border: 1px solid var(--border);
		border-radius: 999px;
		padding: 2px 8px;
	}

	.stat-chip.due {
		color: var(--gold);
		border-color: var(--gold);
	}

	.empty-actions {
		display: flex;
		justify-content: center;
		gap: 12px;
		flex-wrap: wrap;
		margin-top: 14px;
	}

	.tag {
		align-self: flex-start;
	}
</style>
