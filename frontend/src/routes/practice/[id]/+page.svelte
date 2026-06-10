<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import AttemptRecorder from '$lib/components/AttemptRecorder.svelte';
	import AudioPlayer from '$lib/components/AudioPlayer.svelte';
	import GradeBar from '$lib/components/GradeBar.svelte';
	import PromptCard from '$lib/components/PromptCard.svelte';
	import { api } from '$lib/api/client';
	import type {
		AttemptRating,
		LanguageProfile,
		Media,
		PracticeItem,
		PracticeSession,
		Revision
	} from '$lib/api/types';
	import type { AttemptRecording } from '$lib/audio/recorder';
	import { registerMedia } from '$lib/utils/mediaRegistry';
	import { clearActiveSession, rememberActiveSession } from '$lib/utils/recovery';

	let session: PracticeSession | null = $state(null);
	let revision: Revision | null = $state(null);
	let profile: LanguageProfile | null = $state(null);
	let passageTitle = $state('');
	let error = $state('');
	let loading = $state(true);

	let revealed = $state(false);
	let submitting = $state(false);
	let savingBest = $state(false);
	let pendingMediaId: string | null = $state(null);
	let lastFeedback = $state('');
	let tally: Record<AttemptRating, number> = $state({ clean: 0, hesitant: 0, incorrect: 0, revealed: 0 });
	// Recording is deliberately opt-in (grill D2): speaking aloud is the
	// learning act; the mic is for occasionally capturing a best take.
	const MIC_KEY = 'rhapsode.micEnabled';
	let micEnabled = $state(false);

	// Latency measures focused time only (grill A2): the clock pauses while
	// the window is blurred or the tab hidden, so alt-tabbing doesn't inflate
	// the hesitation signal or the session-length estimator.
	let focusedMs = $state(0);
	let runningSince: number | null = $state(null);

	function clockActive(): boolean {
		return !document.hidden && document.hasFocus();
	}

	function pauseClock() {
		if (runningSince !== null) {
			focusedMs += performance.now() - runningSince;
			runningSince = null;
		}
	}

	function resumeClock() {
		if (runningSince === null && clockActive()) {
			runningSince = performance.now();
		}
	}

	function elapsedFocusedMs(): number {
		return focusedMs + (runningSince !== null ? performance.now() - runningSince : 0);
	}

	const items = $derived.by(() =>
		[...(session?.items ?? [])].sort((a, b) => a.position - b.position)
	);
	const currentItem = $derived.by((): PracticeItem | null => {
		if (!session || session.status !== 'active') return null;
		// Honor the persisted cursor first, then fall back to any incomplete
		// item so out-of-order server state still resumes cleanly.
		const fromIndex = items.slice(session.current_index).find((item) => !item.completed);
		return fromIndex ?? items.find((item) => !item.completed) ?? null;
	});
	const doneCount = $derived(items.filter((item) => item.completed).length);
	const segmentById = $derived.by(
		() => new Map((revision?.segments ?? []).map((segment) => [segment.id, segment]))
	);
	// Listed from the backend so imported scholar recitations appear too.
	let referenceMedia: Media[] = $state([]);
	const revealText = $derived.by(() => {
		if (!currentItem) return null;
		const prompt = currentItem.prompt as Record<string, unknown>;
		if (typeof prompt.target_text === 'string') return prompt.target_text;
		if (currentItem.mode === 'full_passage') return revision?.source_text ?? null;
		return currentItem.segment_id ? (segmentById.get(currentItem.segment_id)?.text ?? null) : null;
	});

	$effect(() => {
		// restart the latency clock and reveal state per item
		void currentItem?.id;
		revealed = false;
		focusedMs = 0;
		runningSince = clockActive() ? performance.now() : null;
		pendingMediaId = null;
	});

	onMount(async () => {
		micEnabled = localStorage.getItem(MIC_KEY) === 'true';
		try {
			session = await api.getSession(page.params.id ?? '');
			revision = await api.getRevision(session.revision_id);
			const [languages, passage, reference] = await Promise.all([
				api.listLanguages(),
				api.getPassage(revision.passage_id),
				api.listMedia(revision.id, 'reference')
			]);
			referenceMedia = reference;
			passageTitle = passage.title;
			profile = languages.find((candidate) => candidate.id === passage.language_profile_id) ?? null;
			if (session.status === 'active') {
				rememberActiveSession({
					sessionId: session.id,
					revisionId: revision.id,
					passageTitle: passage.title
				});
			}
		} catch (cause) {
			error = `Could not load the session: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			loading = false;
		}
	});

	async function grade(rating: AttemptRating) {
		if (!session || !currentItem || submitting) return;
		submitting = true;
		error = '';
		try {
			const result = await api.submitAttempt(session.id, {
				item_id: currentItem.id,
				rating: revealed ? 'revealed' : rating,
				latency_ms: Math.max(0, Math.round(elapsedFocusedMs())),
				media_asset_id: pendingMediaId
			});
			tally = { ...tally, [result.attempt.rating as AttemptRating]: tally[result.attempt.rating as AttemptRating] + 1 };
			lastFeedback = result.mastery_stage
				? `${result.attempt.rating} · mastery ${result.mastery_stage}${result.due_at ? ` · next ${new Date(result.due_at).toLocaleDateString()}` : ''}`
				: result.attempt.rating;
			session = result.session;
			if (items.every((item) => item.completed)) await finish();
		} catch (cause) {
			error = `Could not submit the attempt: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			submitting = false;
		}
	}

	async function finish() {
		if (!session) return;
		if (session.status === 'active') session = await api.completeSession(session.id);
		clearActiveSession(session.id);
	}

	function toggleMic() {
		micEnabled = !micEnabled;
		localStorage.setItem(MIC_KEY, String(micEnabled));
	}

	async function saveBest(recording: AttemptRecording) {
		if (!session || !revision || !currentItem) return;
		savingBest = true;
		try {
			const media = await api.uploadMedia(recording.blob, 'saved_best', {
				revisionId: revision.id,
				segmentId: currentItem.segment_id ?? undefined,
				filename: `best-${passageTitle.replaceAll(/\s+/g, '-').toLowerCase()}-${currentItem.position + 1}.webm`
			});
			registerMedia({
				id: media.id,
				category: 'saved_best',
				revisionId: revision.id,
				segmentId: currentItem.segment_id,
				name: media.original_name,
				mimeType: media.mime_type,
				createdAt: media.created_at
			});
			pendingMediaId = media.id;
		} catch (cause) {
			error = `Could not save the recording: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			savingBest = false;
		}
	}
</script>

<svelte:window onblur={pauseClock} onfocus={resumeClock} />
<svelte:document onvisibilitychange={() => (document.hidden ? pauseClock() : resumeClock())} />

{#if loading}
	<p class="muted">Loading…</p>
{:else if !session}
	<p class="error-banner" role="alert">{error || 'Session not found.'}</p>
{:else}
	<header class="head">
		<div>
			<span class="eyebrow">Practice session</span>
			<h1>{passageTitle}</h1>
		</div>
		<span class="tag">{doneCount}/{items.length} items</span>
	</header>

	<div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax={items.length} aria-valuenow={doneCount}>
		{#each items as item (item.id)}
			<span
				class="dot"
				class:done={item.completed}
				class:current={item.id === currentItem?.id}
				title="#{item.position + 1} {item.mode}"
			></span>
		{/each}
	</div>

	{#if error}<p class="error-banner" role="alert">{error}</p>{/if}

	{#if currentItem}
		<PromptCard
			item={currentItem}
			{profile}
			{revealed}
			{revealText}
			onReveal={() => (revealed = true)}
		/>

		{#if referenceMedia.length}
			{#if currentItem.mode === 'shadowing'}
				<!-- Shadowing IS listening: every recording, expanded. -->
				{#each referenceMedia as media (media.id)}
					<AudioPlayer src={api.mediaUrl(media.id)} title={media.original_name} storageKey={media.id} />
				{/each}
			{:else}
				<details class="reference">
					<summary class="muted small">Reference audio ({referenceMedia.length})</summary>
					{#each referenceMedia as media (media.id)}
						<AudioPlayer src={api.mediaUrl(media.id)} title={media.original_name} storageKey={media.id} />
					{/each}
				</details>
			{/if}
		{/if}

		{#if micEnabled}
			{#key currentItem.id}
				<AttemptRecorder onSaveBest={saveBest} saving={savingBest} />
			{/key}
		{/if}
		<button class="mic-toggle" onclick={toggleMic} aria-pressed={micEnabled}>
			{micEnabled ? '🎙 recording enabled' : '🎙 enable recording'}
		</button>

		<GradeBar onGrade={grade} disabled={submitting} />
		{#if revealed}
			<p class="muted small">Text was revealed — this attempt is graded as “revealed”.</p>
		{/if}
		{#if lastFeedback}
			<p class="feedback">{lastFeedback}</p>
		{/if}
	{:else}
		<div class="card summary">
			<span class="eyebrow">Session complete</span>
			<h2>Well recited.</h2>
			<ul>
				<li><span class="clean">clean</span> × {tally.clean}</li>
				<li><span class="hesitant">hesitant</span> × {tally.hesitant}</li>
				<li><span class="incorrect">incorrect</span> × {tally.incorrect}</li>
				<li><span class="revealed">revealed</span> × {tally.revealed}</li>
			</ul>
			<p class="muted small">
				Counts reflect attempts submitted in this browser tab; the durable record lives in review
				analytics.
			</p>
			<div class="row">
				<a href="/review"><button class="primary">Open review →</button></a>
				<a href="/practice"><button>All sessions</button></a>
			</div>
		</div>
	{/if}
{/if}

<style>
	.head {
		display: flex;
		justify-content: space-between;
		align-items: flex-end;
	}

	.head h1 {
		margin: 6px 0 10px;
	}

	.progress {
		display: flex;
		gap: 5px;
		flex-wrap: wrap;
		margin: 10px 0 18px;
	}

	.dot {
		width: 14px;
		height: 14px;
		border-radius: 4px;
		background: var(--surface-2);
		border: 1px solid var(--border);
	}

	.dot.done {
		background: var(--green);
		border-color: var(--green);
	}

	.dot.current {
		border-color: var(--gold);
		box-shadow: 0 0 8px var(--gold-glow), 0 0 4px var(--gold);
	}

	:global(.prompt) {
		margin-bottom: 14px;
	}

	:global(.recorder) {
		margin: 14px 0;
	}

	.small {
		font-size: 0.82rem;
	}

	.mic-toggle {
		font-size: 0.78rem;
		color: var(--muted, #8b95a8);
		background: none;
		border: none;
		padding: 2px 0;
		margin-bottom: 10px;
		cursor: pointer;
	}

	.reference {
		margin: 14px 0;
	}

	.reference summary {
		cursor: pointer;
	}

	.feedback {
		font-family: var(--font-mono);
		font-size: 0.8rem;
		color: var(--green);
	}

	.summary ul {
		list-style: none;
		padding: 0;
		display: flex;
		gap: 22px;
		font-family: var(--font-mono);
	}

	.summary .clean { color: var(--green); }
	.summary .hesitant { color: var(--gold); }
	.summary .incorrect { color: var(--red); }
	.summary .revealed { color: var(--purple); }

	.summary .row {
		display: flex;
		gap: 10px;
	}
</style>
