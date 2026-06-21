<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import AudioPlayer from '$lib/components/AudioPlayer.svelte';
	import LineAligner from '$lib/components/LineAligner.svelte';
	import SegmentEditor from '$lib/components/SegmentEditor.svelte';
	import SegmentText from '$lib/components/SegmentText.svelte';
	import { api, isConflict } from '$lib/api/client';
	import type { LanguageProfile, Media, PassageDetail, PracticeMode, Revision } from '$lib/api/types';
	import { PRACTICE_MODES } from '$lib/api/types';
	import { profileLayers, supportsRuby, supportsVertical } from '$lib/utils/language';
	import { rememberActiveSession } from '$lib/utils/recovery';
	import {
		buildSegmentTree,
		draftsToInputs,
		presentKinds,
		segmentsToDrafts,
		type DraftSegment
	} from '$lib/utils/segments';

	let passage: PassageDetail | null = $state(null);
	let revision: Revision | null = $state(null);
	let profile: LanguageProfile | null = $state(null);
	let error = $state('');
	let loading = $state(true);

	// reading view options
	let enabledLayers: string[] = $state([]);
	let showRuby = $state(true);
	let vertical = $state(false);
	let showCues = $state(false);

	// editor
	let drafts: DraftSegment[] = $state([]);
	let editing = $state(false);
	let saving = $state(false);
	let conflict = $state(false);
	let forkSourceText = $state('');

	// audio — listed from the backend so reference tracks imported outside
	// this browser (e.g. the scholar-recitation import script) still appear.
	let referenceMedia: Media[] = $state([]);
	let uploading = $state(false);
	// Which reference track's manual line-aligner is open (by media id).
	let aligning: string | null = $state(null);

	// practice launcher
	let chosenModes: PracticeMode[] = $state(['cue_recall']);
	let chosenKinds: string[] = $state(['line']);
	let startingSession = $state(false);
	// Time budget chips (grill A3): null = the planner's fixed item cap.
	const MINUTES_KEY = 'rhapsode.sessionMinutes';
	const MINUTE_CHOICES = [5, 15, 30];
	let minutesChoice: number | null = $state(null);

	// prep assistant
	let suggesting = $state(false);
	let prepSummary = $state('');

	// Junctures are derived drill targets, not text: they practice but never
	// display or edit.
	const visibleSegments = $derived.by(() =>
		(revision?.segments ?? []).filter((segment) => segment.kind !== 'juncture')
	);
	const lineSegments = $derived(
		visibleSegments
			.filter((segment) => segment.kind === 'line')
			.slice()
			.sort((a, b) => a.ordinal - b.ordinal)
	);
	const tree = $derived.by(() => buildSegmentTree(visibleSegments));
	const kinds = $derived.by(() => presentKinds(visibleSegments));
	const layerChoices = $derived.by(() => {
		const declared = profileLayers(profile).map((entry) => entry.layer);
		const present = new Set(
			(revision?.segments ?? []).flatMap((segment) =>
				(segment.annotations ?? []).map((annotation) => annotation.layer)
			)
		);
		return [...new Set([...declared, ...present])];
	});

	onMount(() => {
		const stored = Number(localStorage.getItem(MINUTES_KEY));
		minutesChoice = MINUTE_CHOICES.includes(stored) ? stored : null;
		void load();
	});

	async function load() {
		loading = true;
		error = '';
		try {
			passage = await api.getPassage(page.params.id ?? '');
			revision = passage.active_revision ?? null;
			const languages = await api.listLanguages();
			profile = languages.find((candidate) => candidate.id === passage?.language_profile_id) ?? null;
			enabledLayers = [];
			if (revision) {
				drafts = segmentsToDrafts(visibleSegments);
				forkSourceText = revision.source_text;
				referenceMedia = await api.listMedia(revision.id, 'reference');
				if (!chosenKinds.every((kind) => kinds.includes(kind)) && kinds.length) {
					chosenKinds = [kinds.includes('line') ? 'line' : kinds[0]];
				}
			}
		} catch (cause) {
			error = `Could not load the passage: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			loading = false;
		}
	}

	function toggle(list: string[], value: string): string[] {
		return list.includes(value) ? list.filter((entry) => entry !== value) : [...list, value];
	}

	async function saveSegments() {
		if (!revision) return;
		saving = true;
		error = '';
		try {
			revision = await api.replaceSegments(revision.id, draftsToInputs(drafts, profile));
			editing = false;
		} catch (cause) {
			if (isConflict(cause)) {
				// Practiced revisions are immutable by contract; offer a fork.
				conflict = true;
			} else {
				error = `Could not save segments: ${cause instanceof Error ? cause.message : cause}`;
			}
		} finally {
			saving = false;
		}
	}

	async function forkRevision() {
		if (!passage) return;
		saving = true;
		error = '';
		try {
			await api.createRevision(passage.id, {
				source_text: forkSourceText,
				hierarchy: revision?.hierarchy ?? {},
				segments: draftsToInputs(drafts, profile)
			});
			conflict = false;
			editing = false;
			await load();
		} catch (cause) {
			error = `Could not create a new revision: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			saving = false;
		}
	}

	async function uploadReference(event: Event) {
		const input = event.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		if (!file || !revision) return;
		uploading = true;
		error = '';
		try {
			await api.uploadMedia(file, 'reference', {
				revisionId: revision.id,
				filename: file.name
			});
			referenceMedia = await api.listMedia(revision.id, 'reference');
		} catch (cause) {
			error = `Could not upload audio: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			uploading = false;
			input.value = '';
		}
	}

	async function removeReference(mediaId: string) {
		await api.deleteMedia(mediaId);
		if (revision) referenceMedia = await api.listMedia(revision.id, 'reference');
	}

	function pickMinutes(value: number | null) {
		minutesChoice = value;
		if (value === null) localStorage.removeItem(MINUTES_KEY);
		else localStorage.setItem(MINUTES_KEY, String(value));
	}

	async function suggestPrep() {
		if (!revision) return;
		suggesting = true;
		error = '';
		prepSummary = '';
		try {
			const result = await api.suggestPrep(revision.id);
			prepSummary = Object.entries(result.written)
				.map(([layer, count]) => `${count} ${layer}${count === 1 ? '' : 's'}`)
				.join(', ');
			await load();
		} catch (cause) {
			error = `Could not draft prep: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			suggesting = false;
		}
	}

	async function startSession(smart = false) {
		if (!revision || !passage) return;
		startingSession = true;
		error = '';
		try {
			// Omitting modes asks the backend coach to pick one per segment
			// from its mastery stage; omitting segment_kinds lets it pick the
			// passage's natural grain (plus junctures).
			const session = await api.createSession({
				revision_id: revision.id,
				...(smart
					? { ...(minutesChoice !== null ? { minutes: minutesChoice } : {}) }
					: { modes: chosenModes, segment_kinds: chosenKinds })
			});
			rememberActiveSession({
				sessionId: session.id,
				revisionId: revision.id,
				passageTitle: passage.title
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
{:else if !passage}
	<p class="error-banner" role="alert">{error || 'Passage not found.'}</p>
{:else}
	<header class="head">
		<div>
			<span class="eyebrow">{profile?.name ?? 'Passage'}{revision ? ` · revision ${revision.revision_number}` : ''}{revision?.practiced ? ' · practiced (immutable)' : ''}</span>
			<h1>{passage.title}</h1>
			{#if passage.description}<p class="muted">{passage.description}</p>{/if}
		</div>
	</header>

	{#if error}<p class="error-banner" role="alert">{error}</p>{/if}

	{#if revision}
		<section class="card reading">
			<div class="toolbar">
				<span class="eyebrow">Reading view</span>
				{#each layerChoices as layer (layer)}
					<button
						class:active={enabledLayers.includes(layer)}
						aria-pressed={enabledLayers.includes(layer)}
						onclick={() => (enabledLayers = toggle(enabledLayers, layer))}
					>{layer}</button>
				{/each}
				{#if supportsRuby(profile)}
					<button class:active={showRuby} aria-pressed={showRuby} onclick={() => (showRuby = !showRuby)}>ruby</button>
				{/if}
				{#if supportsVertical(profile)}
					<button class:active={vertical} aria-pressed={vertical} onclick={() => (vertical = !vertical)}>vertical</button>
				{/if}
				<button class:active={showCues} aria-pressed={showCues} onclick={() => (showCues = !showCues)}>cues</button>
			</div>
			<div class="text-flow" class:vertical-text={vertical}>
				{#each tree as node (node.id)}
					<SegmentText {node} {profile} layers={enabledLayers} {showRuby} {showCues} />
				{/each}
			</div>
		</section>

		<div class="columns">
			<section class="card">
				<span class="eyebrow">Reference audio</span>
				<p class="muted small">Trusted recordings of this revision. Loop, set cue points, slow down.</p>
				<label class="upload">
					<input type="file" accept="audio/*" onchange={uploadReference} disabled={uploading} />
				</label>
				{#each referenceMedia as media (media.id)}
					<div class="media">
						<AudioPlayer src={api.mediaUrl(media.id)} title={media.original_name} storageKey={media.id} cuePoints={media.cue_points ?? []} />
						<div class="media-actions">
							{#if lineSegments.length}
								<button
									class:active={aligning === media.id}
									aria-pressed={aligning === media.id}
									onclick={() => (aligning = aligning === media.id ? null : media.id)}
								>
									{(media.cue_points ?? []).length ? '✎ Re-align lines' : '⊺ Align lines'}
								</button>
							{/if}
							<button class="danger" onclick={() => removeReference(media.id)}>Delete</button>
						</div>
						{#if aligning === media.id}
							<LineAligner
								{media}
								lines={lineSegments}
								{profile}
								onSaved={(updated) => {
									referenceMedia = referenceMedia.map((item) => (item.id === updated.id ? updated : item));
									aligning = null;
								}}
							/>
						{/if}
					</div>
				{:else}
					<p class="muted small">No reference audio yet.</p>
				{/each}
			</section>

			<section class="card">
				<span class="eyebrow">Practice</span>
				<div class="choices" role="group" aria-label="Session length">
					<button
						class:active={minutesChoice === null}
						aria-pressed={minutesChoice === null}
						onclick={() => pickMinutes(null)}
					>standard</button>
					{#each MINUTE_CHOICES as minutes (minutes)}
						<button
							class:active={minutesChoice === minutes}
							aria-pressed={minutesChoice === minutes}
							onclick={() => pickMinutes(minutes)}
						>≈{minutes} min</button>
					{/each}
				</div>
				<button
					class="primary start"
					disabled={startingSession}
					onclick={() => startSession(true)}
				>{startingSession ? 'Starting…' : '✦ Smart session'}</button>
				<p class="muted small">
					The coach picks a mode per segment from its mastery: scaffold new lines, cue
					learning ones, cold-start mastered ones, drill weak links and line junctures.
					Session length comes from your own pace in past attempts.
				</p>
				<details>
					<summary class="muted small">Choose modes manually</summary>
				<div class="choices">
					{#each PRACTICE_MODES as mode (mode)}
						<button
							class:active={chosenModes.includes(mode)}
							aria-pressed={chosenModes.includes(mode)}
							onclick={() => (chosenModes = toggle(chosenModes, mode) as PracticeMode[])}
						>{mode.replaceAll('_', ' ')}</button>
					{/each}
				</div>
				<div class="choices">
					{#each kinds as kind (kind)}
						<button
							class:active={chosenKinds.includes(kind)}
							aria-pressed={chosenKinds.includes(kind)}
							onclick={() => (chosenKinds = toggle(chosenKinds, kind))}
						>{kind}s</button>
					{/each}
				</div>
				<button
					class="start"
					disabled={startingSession || chosenModes.length === 0 || chosenKinds.length === 0}
					onclick={() => startSession()}
				>{startingSession ? 'Starting…' : '▶ Start manual session'}</button>
				</details>
			</section>
		</div>

		<section class="card">
			<div class="toolbar">
				<span class="eyebrow">Segments &amp; annotations</span>
				<button onclick={() => (editing = !editing)}>{editing ? 'Close editor' : 'Edit'}</button>
				<button disabled={suggesting} onclick={suggestPrep} title="Gemini drafts cues, word splits, readings, glosses, and translations for lines that don't have them yet. Nothing you wrote is touched.">
					{suggesting ? 'Drafting…' : '✦ Draft prep'}
				</button>
				{#if editing}
					<button class="primary" disabled={saving} onclick={saveSegments}>
						{saving ? 'Saving…' : 'Save segments'}
					</button>
				{/if}
			</div>
			{#if prepSummary}
				<p class="muted small">Drafted: {prepSummary}. Edit or delete anything that misses.</p>
			{/if}
			{#if revision.practiced && editing}
				<p class="muted small">
					This revision has been practiced and is immutable — saving will offer to fork a new revision.
				</p>
			{/if}
			{#if editing}
				<SegmentEditor bind:drafts {profile} />
			{/if}
		</section>

		{#if conflict}
			<div class="card conflict" role="alertdialog" aria-label="Revision conflict">
				<span class="eyebrow">Practiced revisions are immutable</span>
				<p>
					The backend rejected the edit (409). Create revision
					{revision.revision_number + 1} with your changes instead — review history stays attached
					to revision {revision.revision_number}.
				</p>
				<label for="fork-source">Source text for the new revision</label>
				<textarea id="fork-source" rows="4" bind:value={forkSourceText} class="passage-text"></textarea>
				<div class="toolbar">
					<button class="primary" disabled={saving} onclick={forkRevision}>
						{saving ? 'Creating…' : 'Create new revision'}
					</button>
					<button onclick={() => (conflict = false)}>Cancel</button>
				</div>
			</div>
		{/if}
	{:else}
		<p class="error-banner">This passage has no active revision.</p>
	{/if}
{/if}

<style>
	.head h1 {
		margin: 6px 0 4px;
	}

	section {
		margin-bottom: 18px;
	}

	.toolbar {
		display: flex;
		gap: 8px;
		align-items: center;
		flex-wrap: wrap;
		margin-bottom: 12px;
	}

	.toolbar button {
		font-size: 0.78rem;
		padding: 5px 10px;
	}

	button.active {
		border-color: var(--gold);
		color: var(--gold);
		background: var(--gold-glow);
	}

	.text-flow.vertical-text {
		display: flex;
		overflow-x: auto;
	}

	.columns {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 18px;
		margin-bottom: 18px;
	}

	.small {
		font-size: 0.82rem;
	}

	.choices {
		display: flex;
		gap: 6px;
		flex-wrap: wrap;
		margin: 10px 0;
	}

	.choices button {
		font-size: 0.75rem;
		padding: 5px 10px;
	}

	.media {
		display: flex;
		flex-direction: column;
		gap: 6px;
		margin: 10px 0;
	}

	.media-actions {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
	}

	.media-actions button {
		font-size: 0.72rem;
		padding: 4px 10px;
	}

	.media-actions button.active {
		border-color: var(--gold);
		color: var(--gold);
	}

	.upload input {
		border-style: dashed;
		padding: 14px;
	}

	.start {
		width: 100%;
		padding: 12px;
		margin-top: 8px;
	}

	details summary {
		cursor: pointer;
		margin-top: 10px;
	}

	.conflict {
		border-color: var(--purple);
	}

	@media (max-width: 900px) {
		.columns {
			grid-template-columns: 1fr;
		}
	}
</style>
