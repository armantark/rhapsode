<script lang="ts">
	import { onDestroy } from 'svelte';
	import { Recorder, disposeRecording, type AttemptRecording } from '$lib/audio/recorder';

	let {
		onSaveBest = null,
		saving = false
	}: {
		/** Present only when a best take can be persisted for this item. */
		onSaveBest?: ((recording: AttemptRecording) => Promise<void>) | null;
		saving?: boolean;
	} = $props();

	const recorder = new Recorder();
	let recording = $state(false);
	// getUserMedia can hang on an unanswered browser permission prompt, so the
	// pending state is shown rather than leaving the button apparently dead.
	let requesting = $state(false);
	let take: AttemptRecording | null = $state(null);
	let micError = $state('');
	let savedTakeUrl = $state('');

	// The parent remounts this component per practice item ({#key}), so
	// unmount is where the mic and any unsaved take get released.
	onDestroy(() => {
		recorder.releaseStream();
		disposeRecording(take);
	});

	async function start() {
		micError = '';
		discard();
		requesting = true;
		try {
			await recorder.start();
			recording = true;
		} catch (error) {
			micError =
				error instanceof DOMException && error.name === 'NotAllowedError'
					? 'Microphone access was denied. Allow it in the browser to record attempts.'
					: `Could not start recording: ${error instanceof Error ? error.message : error}`;
		} finally {
			requesting = false;
		}
	}

	async function stop() {
		take = await recorder.stop();
		recording = false;
	}

	function discard() {
		disposeRecording(take);
		take = null;
	}

	async function saveBest() {
		if (take && onSaveBest) {
			await onSaveBest(take);
			savedTakeUrl = take.url;
		}
	}
</script>

<div class="recorder card">
	<div class="row">
		<span class="eyebrow">Attempt recording</span>
		<span class="muted note">browser-local, discarded unless saved as best</span>
	</div>
	{#if micError}
		<p class="error-banner" role="alert">{micError}</p>
	{/if}
	<div class="row">
		{#if recording}
			<button class="danger rec-stop" onclick={stop}>■ Stop</button>
			<span class="pulse" aria-hidden="true"></span><span>Recording…</span>
		{:else if requesting}
			<button disabled>● Record</button>
			<span class="muted">Waiting for microphone permission — check the browser prompt…</span>
		{:else}
			<button class="primary" onclick={start}>● Record</button>
		{/if}
		{#if take}
			<audio controls src={take.url} aria-label="Play back your attempt"></audio>
			<span class="muted">{(take.durationMs / 1000).toFixed(1)}s</span>
			<button onclick={discard}>Discard</button>
			{#if onSaveBest}
				<button disabled={saving || savedTakeUrl === take.url} onclick={saveBest}>
					{savedTakeUrl === take.url ? '✓ Saved best' : saving ? 'Saving…' : '★ Save as best'}
				</button>
			{/if}
		{/if}
	</div>
</div>

<style>
	.recorder {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.row {
		display: flex;
		align-items: center;
		gap: 10px;
		flex-wrap: wrap;
	}

	.note {
		font-size: 0.78rem;
	}

	audio {
		height: 36px;
	}

	.pulse {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: var(--red);
		animation: pulse 1s infinite alternate;
	}

	@keyframes pulse {
		from { opacity: 1; }
		to { opacity: 0.25; }
	}
</style>
