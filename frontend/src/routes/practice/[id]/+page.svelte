<script lang="ts">
	import Skeleton from '$lib/components/Skeleton.svelte';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import AttemptRecorder from '$lib/components/AttemptRecorder.svelte';
	import AudioPlayer from '$lib/components/AudioPlayer.svelte';
	import GradeBar from '$lib/components/GradeBar.svelte';
	import PromptCard from '$lib/components/PromptCard.svelte';
	import { api, isConflict } from '$lib/api/client';
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
	import { buildSegmentTree } from '$lib/utils/segments';
	import { profileLayers } from '$lib/utils/language';
	import {
		isSoundEnabled,
		playComplete,
		playGrade,
		playUndo,
		setSoundEnabled
	} from '$lib/utils/feedback';

	const RATING_LABELS: Record<AttemptRating, string> = {
		clean: 'Easy',
		hesitant: 'Good',
		incorrect: 'Hard',
		revealed: 'Again'
	};

	let session: PracticeSession | null = $state(null);
	// A session can span one passage (revision_id) or a whole collection, where
	// each item carries its own revision_id. We hold every revision the session
	// touches and switch the active one per item, so passage-specific context
	// (segments, profile, reference audio) always matches the card on screen.
	let revisionMap: Record<string, Revision> = $state({});
	let profileMap: Record<string, LanguageProfile> = $state({});
	let titleMap: Record<string, string> = $state({});
	let mediaMap: Record<string, Media[]> = $state({});
	let collectionName = $state('');
	let error = $state('');
	let loading = $state(true);

	let revealed = $state(false);
	let acquisitionReady = $state(false);
	let segmentNote: string | null = $state(null);
	let submitting = $state(false);
	let undoing = $state(false);
	let savingBest = $state(false);
	let pendingMediaId: string | null = $state(null);
	let lastFeedback = $state('');
	let tally: Record<AttemptRating, number> = $state({ clean: 0, hesitant: 0, incorrect: 0, revealed: 0 });
	// Client-side stack of the ratings submitted this tab, so Cmd+Z can roll the
	// on-screen tally back in step with the server-side review-state undo.
	const history: AttemptRating[] = [];
	// Juicy feedback: a brief full-card colour pulse keyed to the grade, plus
	// tuned tones (see utils/feedback). flashToken retriggers the CSS animation.
	let flash: AttemptRating | null = $state(null);
	let flashToken = $state(0);
	let celebrate = $state(false);
	// What's still waiting after this session — the completion screen offers
	// to keep the momentum rolling instead of dead-ending at analytics.
	let remainingDue: number | null = $state(null);
	let continuing = $state(false);

	async function continueWithDue() {
		continuing = true;
		try {
			const next = await api.createSession({ due_only: true });
			// A same-route param change would not remount this page (data loads
			// in onMount), so take a full navigation to the fresh session.
			window.location.assign(`/practice/${next.id}`);
		} catch (cause) {
			error = `Could not start the next session: ${cause instanceof Error ? cause.message : cause}`;
			continuing = false;
		}
	}
	let soundOn = $state(true);
	// Consecutive clean recalls this tab — a competence/curiosity driver that
	// escalates the reward (brighter tone, growing chip).
	let streak = $state(0);

	function trailingCleans(): number {
		let count = 0;
		for (let i = history.length - 1; i >= 0 && history[i] === 'clean'; i -= 1) count += 1;
		return count;
	}
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

	const items = $derived.by((): PracticeItem[] =>
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
	// The active revision follows the current card (collection sessions) and
	// falls back to the session's own revision (single-passage sessions).
	// The cast works around a svelte-check flow-analysis quirk where the
	// $state-backed `session` is narrowed to `never` inside this $derived; the
	// runtime type is unaffected. currentItem (itself a $derived) needs no cast.
	const activeRevisionId = $derived(
		currentItem?.revision_id ?? (session as PracticeSession | null)?.revision_id ?? null
	);
	const revision = $derived(activeRevisionId ? (revisionMap[activeRevisionId] ?? null) : null);
	const profile = $derived(activeRevisionId ? (profileMap[activeRevisionId] ?? null) : null);
	const referenceMedia = $derived(activeRevisionId ? (mediaMap[activeRevisionId] ?? []) : []);
	const passageTitle = $derived(activeRevisionId ? (titleMap[activeRevisionId] ?? '') : '');
	const passageReference = $derived(revision?.reference_label || passageTitle);
	// Collection sessions show the collection name in the header but still need
	// the per-card passage title for saved-best filenames.
	const sessionTitle = $derived(collectionName || passageTitle);
	const segmentById = $derived.by(
		() => new Map((revision?.segments ?? []).map((segment) => [segment.id, segment]))
	);
	// The segment subtree (with token children + annotations) for the card, so
	// the checked answer can show gloss/translation/meter interlinearly.
	const nodeById = $derived.by(() => {
		const map = new Map<string, ReturnType<typeof buildSegmentTree>[number]>();
		const walk = (nodes: ReturnType<typeof buildSegmentTree>) => {
			for (const n of nodes) {
				map.set(n.id, n);
				walk(n.children);
			}
		};
		walk(buildSegmentTree(revision?.segments ?? []));
		return map;
	});
	const currentNode = $derived(
		currentItem?.segment_id ? (nodeById.get(currentItem.segment_id) ?? null) : null
	);
	const allNodes = $derived([...nodeById.values()]);
	// Layer toggles for the flashcard (translation/gloss/meter), persisted so the
	// choice sticks across cards and sessions.
	const LAYERS_KEY = 'rhapsode.practiceLayers';
	let enabledLayers: string[] = $state([]);
	let layerPrefsLoaded = $state(false);
	let hasStoredLayerPrefs = $state(false);
	const layerChoices = $derived.by(() => {
		const declared = profileLayers(profile)
			.map((entry) => entry.layer)
			.filter((layer) => layer !== 'cue');
		const present = new Set(
			(revision?.segments ?? []).flatMap((segment) =>
				(segment.annotations ?? []).map((annotation) => annotation.layer)
			)
		);
		for (const child of nodeById.values()) {
			for (const annotation of child.annotations ?? []) present.add(annotation.layer);
		}
		return [...new Set([...declared, ...present])].filter((layer) => layer !== 'cue');
	});

	function toggleLayer(layer: string) {
		enabledLayers = enabledLayers.includes(layer)
			? enabledLayers.filter((entry) => entry !== layer)
			: [...enabledLayers, layer];
		localStorage.setItem(LAYERS_KEY, JSON.stringify(enabledLayers));
		hasStoredLayerPrefs = true;
	}
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
		acquisitionReady = false;
		focusedMs = 0;
		runningSince = clockActive() ? performance.now() : null;
		pendingMediaId = null;
	});

	// The session's prompt.hint was frozen at plan time; fetch the live note so
	// edits made this session surface immediately. A 404 is "no note" (null).
	$effect(() => {
		const segmentId = currentItem?.segment_id ?? null;
		segmentNote = null;
		if (!segmentId) return;
		let cancelled = false;
		void api
			.getNote(segmentId)
			.then((fetched) => {
				if (!cancelled) segmentNote = fetched?.text ?? null;
			})
			.catch(() => {});
		return () => {
			cancelled = true;
		};
	});

	async function saveNote(text: string) {
		const segmentId = currentItem?.segment_id;
		if (!segmentId) return;
		const saved = await api.putNote(segmentId, text);
		segmentNote = saved.text;
	}

	onMount(async () => {
		micEnabled = localStorage.getItem(MIC_KEY) === 'true';
		soundOn = isSoundEnabled();
		const storedLayerPrefs = localStorage.getItem(LAYERS_KEY);
		hasStoredLayerPrefs = storedLayerPrefs !== null;
		try {
			const stored = JSON.parse(storedLayerPrefs ?? '[]');
			if (Array.isArray(stored)) enabledLayers = stored.filter((entry) => typeof entry === 'string');
		} catch {
			enabledLayers = [];
		} finally {
			layerPrefsLoaded = true;
		}
		try {
			session = await api.getSession(page.params.id ?? '');
			const languages = await api.listLanguages();
			const languageById = new Map(languages.map((language) => [language.id, language]));
			// Every revision the session touches: a collection session has none on
			// the session itself, so gather them from the items instead.
			const revisionIds = [
				...new Set(
					[
						session.revision_id,
						...(session.items ?? []).map((item) => item.revision_id)
					].filter((id): id is string => !!id)
				)
			];
			// Independent per-revision fetches run in parallel (local backend, small N).
			await Promise.all(
				revisionIds.map(async (revisionId) => {
					const loaded = await api.getRevision(revisionId);
					const [passage, reference] = await Promise.all([
						api.getPassage(loaded.passage_id),
						api.listMedia(loaded.id, 'reference')
					]);
					revisionMap[revisionId] = loaded;
					titleMap[revisionId] = passage.title;
					mediaMap[revisionId] = reference;
					const languageProfile = languageById.get(passage.language_profile_id);
					if (languageProfile) profileMap[revisionId] = languageProfile;
				})
			);
			if (session.collection_id) {
				collectionName = (await api.getCollection(session.collection_id)).name;
			}
			if (session.status === 'active') {
				const firstRevisionId = revisionIds[0] ?? '';
				rememberActiveSession({
					sessionId: session.id,
					revisionId: session.revision_id ?? firstRevisionId,
					passageTitle: collectionName || titleMap[firstRevisionId] || 'Practice'
				});
			}
		} catch (cause) {
			error = `Could not load the session: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			loading = false;
		}
	});

	$effect(() => {
		if (
			!layerPrefsLoaded ||
			hasStoredLayerPrefs ||
			profile?.slug !== 'japanese' ||
			!layerChoices.includes('reading') ||
			enabledLayers.includes('reading')
		) {
			return;
		}
		enabledLayers = [...enabledLayers, 'reading'];
		localStorage.setItem(LAYERS_KEY, JSON.stringify(enabledLayers));
		hasStoredLayerPrefs = true;
	});

	function pulse(rating: AttemptRating) {
		flash = rating;
		const token = flashToken + 1;
		flashToken = token;
		setTimeout(() => {
			if (flashToken === token) flash = null;
		}, 600);
	}

	// Reference pacing for a recital: the summed aligned line spans, available
	// only when every line has one. Arithmetic, not assessment — a fluency
	// mirror shown beside the learner's own focused time.
	const recitalReferenceSeconds = $derived.by(() => {
		if (currentItem?.mode !== 'recital') return null;
		const lineIds = (revision?.segments ?? [])
			.filter((segment) => segment.kind === 'line' || segment.kind === 'chunk')
			.map((segment) => segment.id);
		if (!lineIds.length) return null;
		const spans = new Map<string, number>();
		for (const media of referenceMedia) {
			for (const cue of media.cue_points ?? []) {
				if (cue.segment_id && cue.end != null && !spans.has(cue.segment_id)) {
					spans.set(cue.segment_id, cue.end - cue.time);
				}
			}
		}
		if (!lineIds.every((id) => spans.has(id))) return null;
		return lineIds.reduce((total, id) => total + (spans.get(id) ?? 0), 0);
	});

	async function confirmRecital(stumbledSegmentIds: string[]) {
		// The recital's summary rating mirrors its per-line map: any stumble is
		// a lapse, a clean pass is Good. The backend derives per-line grades.
		const pacing =
			recitalReferenceSeconds !== null
				? ` · you ≈${Math.round(elapsedFocusedMs() / 1000)}s · reference ≈${Math.round(recitalReferenceSeconds)}s`
				: '';
		await grade(stumbledSegmentIds.length ? 'incorrect' : 'hesitant', {
			stumbledSegmentIds,
			feedbackSuffix: pacing
		});
	}

	async function grade(
		rating: AttemptRating,
		recital?: { stumbledSegmentIds: string[]; feedbackSuffix: string }
	) {
		if (!session || !currentItem || submitting || undoing) return;
		submitting = true;
		error = '';
		try {
			// Anki model (grill): showing the answer is a neutral self-check, so
			// the grade is exactly what the learner pressed. We still record that
			// they peeked as an informational flag.
			const result = await api.submitAttempt(session.id, {
				item_id: currentItem.id,
				rating,
				revealed,
				latency_ms: Math.max(0, Math.round(elapsedFocusedMs())),
				media_asset_id: pendingMediaId,
				stumbled_segment_ids: recital?.stumbledSegmentIds ?? null
			});
			const landed = result.attempt.rating as AttemptRating;
			history.push(landed);
			tally = { ...tally, [landed]: tally[landed] + 1 };
			lastFeedback =
				(result.mastery_stage
					? `${RATING_LABELS[landed]} · mastery ${result.mastery_stage}${result.due_at ? ` · next ${new Date(result.due_at).toLocaleDateString()}` : ''}`
					: RATING_LABELS[landed]) + (recital?.feedbackSuffix ?? '');
			session = result.session;
			streak = landed === 'clean' ? streak + 1 : 0;
			playGrade(landed, streak);
			pulse(landed);
			if (items.every((item) => item.completed)) {
				await finish();
				celebrate = true;
				playComplete();
				try {
					remainingDue = (await api.today()).due_count;
				} catch {
					remainingDue = null;
				}
			}
		} catch (cause) {
			error = `Could not submit the attempt: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			submitting = false;
		}
	}

	async function undo() {
		if (!session || submitting || undoing) return;
		undoing = true;
		error = '';
		try {
			session = await api.undoAttempt(session.id);
			celebrate = false;
			const last = history.pop();
			if (last) tally = { ...tally, [last]: Math.max(0, tally[last] - 1) };
			streak = trailingCleans();
			lastFeedback = 'Undid the last card';
			playUndo();
		} catch (cause) {
			if (isConflict(cause)) {
				lastFeedback = 'Nothing left to undo';
			} else {
				error = `Could not undo: ${cause instanceof Error ? cause.message : cause}`;
			}
		} finally {
			undoing = false;
		}
	}

	const canReveal = $derived(
		!!currentItem &&
			!revealed &&
			(currentItem.mode === 'acquisition'
				? acquisitionReady
				: [
				'cue_recall',
				'weak_link',
				'random_start',
				'word_bank',
				'typed_recall',
				'meaning_recall',
				'full_passage',
				'forward_chaining',
				'backward_chaining'
			].includes(currentItem.mode))
	);
	const requiresCheck = $derived(
		!!currentItem && !revealed && (currentItem.mode === 'acquisition' || canReveal)
	);

	function onWindowKeydown(event: KeyboardEvent) {
		const target = event.target as HTMLElement | null;
		if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
		// Space shows the answer to self-check — the natural "flip the card" key.
		if (event.key === ' ' && canReveal) {
			event.preventDefault();
			revealed = true;
			return;
		}
		if (!(event.metaKey || event.ctrlKey) || event.shiftKey || event.key.toLowerCase() !== 'z') {
			return;
		}
		event.preventDefault();
		void undo();
	}

	function toggleSound() {
		soundOn = !soundOn;
		setSoundEnabled(soundOn);
		if (soundOn) playUndo();
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

<svelte:head><title>{sessionTitle ? `${sessionTitle} · Rhapsode` : 'Practice · Rhapsode'}</title></svelte:head>

<svelte:window onblur={pauseClock} onfocus={resumeClock} onkeydown={onWindowKeydown} />
<svelte:document onvisibilitychange={() => (document.hidden ? pauseClock() : resumeClock())} />

{#if flash}
	{#key flashToken}
		<div class="flash {flash}" aria-hidden="true"></div>
	{/key}
{/if}

{#if loading}
	<Skeleton rows={4} card />
{:else if !session}
	<p class="error-banner" role="alert">{error || 'Session not found.'}</p>
{:else}
	<header class="head">
		<div>
			<span class="eyebrow">{collectionName ? 'Collection practice' : 'Practice session'}</span>
			<h1>{sessionTitle}</h1>
			{#if collectionName && passageReference}
				<p class="muted small head-sub">Now practicing · {passageReference}</p>
			{/if}
		</div>
		<div class="head-actions">
			{#if streak >= 2}
				{#key streak}
					<span class="streak" class:hot={streak >= 5} title="{streak} clean in a row">
						🔥 {streak}
					</span>
				{/key}
			{/if}
			<button
				class="ghost"
				onclick={undo}
				disabled={undoing || session.status === 'expired' || (doneCount === 0 && session.status !== 'completed')}
				title="Undo last card (⌘Z)"
			>
				↶ Undo <kbd>⌘Z</kbd>
			</button>
			<button class="ghost" onclick={toggleSound} aria-pressed={soundOn} title="Toggle sound">
				{soundOn ? '🔊' : '🔇'}
			</button>
			<span class="tag">{doneCount}/{items.length} items</span>
		</div>
	</header>

	{#if items.length > 24}
		<!-- A big Today queue would wrap into rows of dots; a slim bar carries
		     the same signal without eating the screen. -->
		<div
			class="progress progress-bar"
			role="progressbar"
			aria-valuemin="0"
			aria-valuemax={items.length}
			aria-valuenow={doneCount}
		>
			<div class="progress-fill" style:width="{(doneCount / Math.max(1, items.length)) * 100}%"></div>
		</div>
	{:else}
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
	{/if}

	{#if error}<p class="error-banner" role="alert">{error}</p>{/if}

	{#if currentItem}
		{#key currentItem.id}
			<div class="card-enter">
				<PromptCard
					item={currentItem}
					{profile}
					{revealed}
					{revealText}
					node={currentNode}
					nodes={allNodes}
					layers={enabledLayers}
					note={segmentNote}
					onReveal={() => (revealed = true)}
					onAcquisitionReady={(ready) => (acquisitionReady = ready)}
					onSaveNote={saveNote}
					onRecitalConfirm={confirmRecital}
				/>
			</div>
		{/key}

		{#if layerChoices.length}
			<div class="layers" role="group" aria-label="Annotation layers">
				<span class="muted small">Show on check:</span>
				{#each layerChoices as layer (layer)}
					<button
						class="layer-chip"
						class:active={enabledLayers.includes(layer)}
						aria-pressed={enabledLayers.includes(layer)}
						onclick={() => toggleLayer(layer)}
					>{layer}</button>
				{/each}
			</div>
		{/if}

		{#if referenceMedia.length}
			{#if currentItem.mode === 'shadowing'}
				<!-- Shadowing IS listening: every recording, expanded. When the
				     audio has been line-aligned, the player jumps straight to this
				     segment's line and loops just its span. -->
				{#each referenceMedia as media (media.id)}
					<AudioPlayer
						src={api.mediaUrl(media.id)}
						title={media.original_name}
						storageKey={media.id}
						cuePoints={media.cue_points}
						focusSegmentId={currentItem.segment_id}
					/>
				{/each}
			{:else}
				<details class="reference">
					<summary class="muted small">Reference audio ({referenceMedia.length})</summary>
					{#each referenceMedia as media (media.id)}
						<AudioPlayer
							src={api.mediaUrl(media.id)}
							title={media.original_name}
							storageKey={media.id}
							cuePoints={media.cue_points}
							focusSegmentId={currentItem.segment_id}
						/>
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

		{#if currentItem.mode !== 'recital'}
			<!-- Recall cards require the check before grading (Anki model: the answer
			     is always seen before the grade). Verbatim errors are exactly the ones
			     the reciter doesn't hear, so grading blind would inflate the schedule.
			     The peek itself stays neutral — it never forces a grade. A recital has
			     no grade bar at all: its stumble map IS the grade. -->
			<GradeBar onGrade={grade} disabled={submitting || requiresCheck} />
			{#if revealed}
				<p class="muted small">
					Answer shown — grade yourself honestly. Pick <strong>Again</strong> only if you
					couldn't recall it.
				</p>
			{:else if requiresCheck}
				<p class="muted small">
					{#if currentItem.mode === 'acquisition' && !acquisitionReady}
						Complete the encounter and reconstruction before the final oral check.
					{:else if currentItem.mode === 'typed_recall'}
						<!-- Space types into the textarea, so pointing at it would lie. -->
						Type from memory, then click “Show answer to check” — grading unlocks after
						the check.
					{:else}
						Recite from memory, then press <kbd>Space</kbd> to check — grading unlocks after
						the check.
					{/if}
				</p>
			{/if}
		{/if}
		{#if lastFeedback}
			<p class="feedback">{lastFeedback}</p>
		{/if}
	{:else if session.status === 'expired'}
		<div class="card summary">
			<span class="eyebrow">Session expired</span>
			<h2>This interrupted session was idle for more than a day.</h2>
			<p class="muted small">
				Its completed attempts are still in review analytics. Start a fresh smart session so the
				coach can plan from your current mastery.
			</p>
			<div class="row">
				<a href="/"><button class="primary">Open library →</button></a>
				<a href="/practice"><button>All sessions</button></a>
			</div>
		</div>
	{:else}
		<div class="card summary" class:celebrate>
			<span class="eyebrow">Session complete</span>
			<h2>Well recited. <span class="laurel">🏛</span></h2>
			<ul>
				<li><span class="clean">Easy</span> × {tally.clean}</li>
				<li><span class="hesitant">Good</span> × {tally.hesitant}</li>
				<li><span class="incorrect">Hard</span> × {tally.incorrect}</li>
				<li><span class="revealed">Again</span> × {tally.revealed}</li>
			</ul>
			<p class="muted small">
				Counts reflect attempts submitted in this browser tab; the durable record lives in review
				analytics. Press <kbd>⌘Z</kbd> to reopen the last card.
			</p>
			<div class="row">
				{#if remainingDue !== null && remainingDue > 0}
					<button class="primary" onclick={continueWithDue} disabled={continuing}>
						{continuing ? 'Building…' : `▶ Keep going — ${remainingDue} still due`}
					</button>
					<a href="/review"><button>Open review →</button></a>
				{:else}
					{#if remainingDue === 0}
						<p class="muted small queue-clear">Queue clear for today. 🏛</p>
					{/if}
					<a href="/review"><button class="primary">Open review →</button></a>
				{/if}
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

	.head-actions {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.ghost {
		background: none;
		border: 1px solid var(--border);
		color: var(--text-dim);
		font-size: 0.78rem;
		padding: 5px 9px;
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}

	.ghost:disabled {
		opacity: 0.4;
	}

	.ghost kbd {
		font-size: 0.68rem;
	}

	/* Grade pulse: a quick coloured wash over the viewport, fading out, so each
	   rating lands with a distinct flash of its own colour. */
	.flash {
		position: fixed;
		inset: 0;
		pointer-events: none;
		z-index: 50;
		opacity: 0;
		animation: flash 0.6s ease-out;
	}

	/* Graded intensity: success flashes brightest, "Again" barely at all, so the
	   feedback differentiates outcomes rather than shouting equally at all. */
	.flash.clean {
		--peak: 0.34;
		background: radial-gradient(circle at 50% 60%, var(--green) 0%, transparent 60%);
	}
	.flash.hesitant {
		--peak: 0.24;
		background: radial-gradient(circle at 50% 60%, var(--gold) 0%, transparent 60%);
	}
	.flash.incorrect {
		--peak: 0.18;
		background: radial-gradient(circle at 50% 60%, var(--red) 0%, transparent 60%);
	}
	.flash.revealed {
		--peak: 0.12;
		background: radial-gradient(circle at 50% 60%, var(--purple) 0%, transparent 60%);
	}

	@keyframes flash {
		0% {
			opacity: var(--peak, 0.3);
			transform: scale(1.04);
		}
		100% {
			opacity: 0;
			transform: scale(1);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.flash {
			animation: none;
			opacity: 0;
		}
		.dot.done,
		.card-enter,
		.streak {
			animation: none;
		}
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

	.progress-bar {
		height: 8px;
		border-radius: 999px;
		background: var(--surface-2);
		border: 1px solid var(--border);
		overflow: hidden;
	}

	.progress-fill {
		height: 100%;
		background: var(--green);
		border-radius: 999px;
		transition: width 0.25s ease-out;
	}

	.dot.done {
		background: var(--green);
		border-color: var(--green);
		animation: dotpop 0.32s cubic-bezier(0.34, 1.56, 0.64, 1);
	}

	@keyframes dotpop {
		0% {
			transform: scale(0.5);
		}
		60% {
			transform: scale(1.35);
		}
		100% {
			transform: scale(1);
		}
	}

	/* OutBack ease: the new card overshoots slightly and settles — springy,
	   organic, not a hard cut. */
	.card-enter {
		animation: cardenter 0.34s cubic-bezier(0.34, 1.56, 0.64, 1);
	}

	@keyframes cardenter {
		0% {
			opacity: 0;
			transform: translateY(8px) scale(0.985);
		}
		100% {
			opacity: 1;
			transform: translateY(0) scale(1);
		}
	}

	.streak {
		font-family: var(--font-mono);
		font-size: 0.82rem;
		color: var(--gold);
		background: rgba(251, 191, 36, 0.1);
		border: 1px solid rgba(251, 191, 36, 0.35);
		border-radius: 999px;
		padding: 3px 9px;
		display: inline-block;
		animation: streakpop 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
	}

	.streak.hot {
		color: #ff8a3d;
		border-color: rgba(255, 138, 61, 0.6);
		box-shadow: 0 0 10px rgba(255, 138, 61, 0.35);
	}

	@keyframes streakpop {
		0% {
			transform: scale(0.7);
		}
		60% {
			transform: scale(1.25);
		}
		100% {
			transform: scale(1);
		}
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

	.layers {
		display: flex;
		align-items: center;
		gap: 7px;
		flex-wrap: wrap;
		margin: 4px 0 12px;
	}

	.layer-chip {
		font-size: 0.74rem;
		padding: 3px 10px;
		text-transform: capitalize;
	}

	.layer-chip.active {
		border-color: var(--gold);
		color: var(--gold);
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
		align-items: center;
		flex-wrap: wrap;
	}

	.queue-clear {
		margin: 0;
	}

	.summary.celebrate {
		animation: rise 0.5s ease-out;
	}

	.summary.celebrate .laurel {
		display: inline-block;
		animation: pop 0.6s ease-out;
	}

	@keyframes rise {
		from {
			opacity: 0;
			transform: translateY(10px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}

	@keyframes pop {
		0% {
			transform: scale(0.4) rotate(-12deg);
		}
		60% {
			transform: scale(1.3) rotate(6deg);
		}
		100% {
			transform: scale(1) rotate(0);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.summary.celebrate,
		.summary.celebrate .laurel {
			animation: none;
		}
	}
</style>
