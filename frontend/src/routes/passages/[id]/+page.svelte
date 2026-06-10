<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import AudioPlayer from '$lib/components/AudioPlayer.svelte';
	import SegmentEditor from '$lib/components/SegmentEditor.svelte';
	import SegmentText from '$lib/components/SegmentText.svelte';
	import { api, isConflict } from '$lib/api/client';
	import type { LanguageProfile, PassageDetail, PracticeMode, Revision } from '$lib/api/types';
	import { PRACTICE_MODES } from '$lib/api/types';
	import { profileLayers, supportsRuby, supportsVertical } from '$lib/utils/language';
	import {
		mediaForRevision,
		forgetMedia,
		registerMedia,
		type MediaRecord
	} from '$lib/utils/mediaRegistry';
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

	// audio
	let referenceMedia: MediaRecord[] = $state([]);
	let uploading = $state(false);

	// practice launcher
	let chosenModes: PracticeMode[] = $state(['cue_recall']);
	let chosenKinds: string[] = $state(['line']);
	let startingSession = $state(false);

	const tree = $derived.by(() => (revision ? buildSegmentTree(revision.segments ?? []) : []));
	const kinds = $derived.by(() => (revision ? presentKinds(revision.segments ?? []) : []));
	const layerChoices = $derived.by(() => {
		const declared = profileLayers(profile).map((entry) => entry.layer);
		const present = new Set(
			(revision?.segments ?? []).flatMap((segment) =>
				(segment.annotations ?? []).map((annotation) => annotation.layer)
			)
		);
		return [...new Set([...declared, ...present])];
	});

	onMount(load);

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
				drafts = segmentsToDrafts(revision.segments ?? []);
				forkSourceText = revision.source_text;
				referenceMedia = mediaForRevision(revision.id, 'reference');
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
			const media = await api.uploadMedia(file, 'reference', {
				revisionId: revision.id,
				filename: file.name
			});
			registerMedia({
				id: media.id,
				category: 'reference',
				revisionId: revision.id,
				segmentId: null,
				name: media.original_name,
				mimeType: media.mime_type,
				createdAt: media.created_at
			});
			referenceMedia = mediaForRevision(revision.id, 'reference');
		} catch (cause) {
			error = `Could not upload audio: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			uploading = false;
			input.value = '';
		}
	}

	async function removeReference(mediaId: string) {
		await api.deleteMedia(mediaId);
		forgetMedia(mediaId);
		if (revision) referenceMedia = mediaForRevision(revision.id, 'reference');
	}

	async function startSession() {
		if (!revision || !passage) return;
		startingSession = true;
		error = '';
		try {
			const session = await api.createSession({
				revision_id: revision.id,
				modes: chosenModes,
				segment_kinds: chosenKinds
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
						<AudioPlayer src={api.mediaUrl(media.id)} title={media.name} storageKey={media.id} />
						<button class="danger" onclick={() => removeReference(media.id)}>Delete</button>
					</div>
				{:else}
					<p class="muted small">No reference audio yet.</p>
				{/each}
			</section>

			<section class="card">
				<span class="eyebrow">Practice</span>
				<p class="muted small">Pick modes and targets, then drill aloud.</p>
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
					class="primary start"
					disabled={startingSession || chosenModes.length === 0 || chosenKinds.length === 0}
					onclick={startSession}
				>{startingSession ? 'Starting…' : '▶ Start session'}</button>
			</section>
		</div>

		<section class="card">
			<div class="toolbar">
				<span class="eyebrow">Segments &amp; annotations</span>
				<button onclick={() => (editing = !editing)}>{editing ? 'Close editor' : 'Edit'}</button>
				{#if editing}
					<button class="primary" disabled={saving} onclick={saveSegments}>
						{saving ? 'Saving…' : 'Save segments'}
					</button>
				{/if}
			</div>
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

	.media .danger {
		align-self: flex-end;
		font-size: 0.72rem;
		padding: 4px 10px;
	}

	.upload input {
		border-style: dashed;
		padding: 14px;
	}

	.start {
		width: 100%;
		padding: 12px;
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
