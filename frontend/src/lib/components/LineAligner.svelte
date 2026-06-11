<script lang="ts">
	import { untrack } from 'svelte';
	import type { CuePoint, LanguageProfile, Media, Segment } from '$lib/api/types';
	import { api } from '$lib/api/client';
	import { fontStack, langCode } from '$lib/utils/language';

	let {
		media,
		lines,
		profile = null,
		onSaved
	}: {
		media: Media;
		/** Line segments in reading order — one cue span will be written per line. */
		lines: Segment[];
		profile?: LanguageProfile | null;
		onSaved?: (media: Media) => void;
	} = $props();

	// Forced alignment can't read reconstructed-pronunciation Greek, and pause
	// auto-detect under-segments a deliberate reading, so the reliable path is
	// the human ear: play the recording and tap at each line's first syllable.
	let audio: HTMLAudioElement | undefined = $state();
	let currentTime = $state(0);
	let duration = $state(0);
	let paused = $state(true);
	let playbackRate = $state(1);
	// starts[i] is the timestamp the learner tapped for line i (null until set).
	// The aligner mounts fresh each time it is opened, so a one-time snapshot of
	// the line count is the intended (non-reactive) initial value.
	const lineCount = untrack(() => lines.length);
	let starts: (number | null)[] = $state(Array.from({ length: lineCount }, () => null));
	let index = $state(0);
	let saving = $state(false);
	let saved = $state(false);
	let error = $state('');

	const lang = $derived(langCode(profile));
	const fonts = $derived(fontStack(profile));
	const allMarked = $derived(starts.every((value) => value !== null));

	function format(seconds: number): string {
		if (!Number.isFinite(seconds)) return '0:00';
		const m = Math.floor(seconds / 60);
		const s = Math.floor(seconds % 60);
		return `${m}:${s.toString().padStart(2, '0')}`;
	}

	function toggle() {
		if (!audio) return;
		if (audio.paused) void audio.play();
		else audio.pause();
	}

	function setRate(rate: number) {
		playbackRate = rate;
		if (audio) audio.playbackRate = rate;
	}

	function mark() {
		if (index >= lines.length) return;
		starts = starts.with(index, currentTime);
		index += 1;
		saved = false;
	}

	function redo(target: number) {
		index = target;
		starts = starts.map((value, i) => (i >= target ? null : value));
		saved = false;
	}

	function reset() {
		starts = Array.from({ length: lineCount }, () => null);
		index = 0;
		saved = false;
	}

	function onKeydown(event: KeyboardEvent) {
		const target = event.target as HTMLElement | null;
		if (target && ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(target.tagName)) return;
		if (event.key === 'm' || event.key === 'M') {
			event.preventDefault();
			mark();
		}
	}

	async function save() {
		if (!allMarked || saving) return;
		saving = true;
		error = '';
		try {
			const cues: CuePoint[] = lines.map((line, i) => {
				const start = starts[i] as number;
				const next = starts[i + 1];
				return {
					label: `line ${i + 1}`,
					time: Math.round(start * 1000) / 1000,
					end: Math.round((next ?? duration) * 1000) / 1000,
					segment_id: line.id
				};
			});
			const updated = await api.setMediaCues(media.id, cues);
			saved = true;
			onSaved?.(updated);
		} catch (cause) {
			error = `Could not save cues: ${cause instanceof Error ? cause.message : cause}`;
		} finally {
			saving = false;
		}
	}
</script>

<svelte:window onkeydown={onKeydown} />

<div class="aligner card">
	<div class="row top">
		<span class="eyebrow">Align lines · {media.original_name}</span>
		<span class="time muted">{format(currentTime)} / {format(duration)}</span>
	</div>
	<p class="muted small">
		Play, then tap <kbd>M</kbd> (or the button) the instant each line begins. Slow it down if you
		need to. The spans are saved per line and drive the shadowing auto-jump.
	</p>

	<audio
		bind:this={audio}
		src={api.mediaUrl(media.id)}
		preload="metadata"
		ontimeupdate={() => (currentTime = audio?.currentTime ?? 0)}
		ondurationchange={() => (duration = audio?.duration ?? 0)}
		onloadedmetadata={() => (duration = audio?.duration ?? 0)}
		onplay={() => (paused = false)}
		onpause={() => (paused = true)}
	></audio>

	<div class="row controls">
		<button class="primary" onclick={toggle}>{paused ? '▶ Play' : '⏸ Pause'}</button>
		<button class="mark" onclick={mark} disabled={index >= lines.length}>
			⊺ Mark line {Math.min(index + 1, lines.length)}
		</button>
		<label class="speed">
			<span class="muted">Speed</span>
			<select value={playbackRate} onchange={(e) => setRate(Number(e.currentTarget.value))}>
				{#each [0.5, 0.65, 0.8, 1] as speed (speed)}
					<option value={speed}>{speed}×</option>
				{/each}
			</select>
		</label>
		<button onclick={reset} disabled={index === 0}>Reset</button>
	</div>

	<ol class="lines">
		{#each lines as line, i (line.id)}
			<li class:done={starts[i] !== null} class:next={i === index}>
				<span class="stamp">{starts[i] !== null ? format(starts[i] as number) : '—'}</span>
				<span class="line-text" {lang} style:font-family={fonts}>{line.text}</span>
				{#if starts[i] !== null}
					<button class="redo" onclick={() => redo(i)} title="Re-mark from here">↺</button>
				{/if}
			</li>
		{/each}
	</ol>

	{#if error}<p class="error-banner" role="alert">{error}</p>{/if}
	<div class="row">
		<button class="primary" onclick={save} disabled={!allMarked || saving}>
			{saved ? '✓ Saved' : saving ? 'Saving…' : 'Save line cues'}
		</button>
		{#if !allMarked}<span class="muted small">{index}/{lines.length} marked</span>{/if}
	</div>
</div>

<style>
	.aligner {
		display: flex;
		flex-direction: column;
		gap: 10px;
		margin-top: 10px;
	}

	.row {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}

	.top {
		justify-content: space-between;
	}

	.time {
		font-family: var(--font-mono);
		font-size: 0.8rem;
	}

	.small {
		font-size: 0.8rem;
	}

	.mark {
		border-color: var(--gold);
		color: var(--gold);
	}

	.speed {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-bottom: 0;
	}

	.speed select {
		width: auto;
	}

	.lines {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.lines li {
		display: flex;
		align-items: baseline;
		gap: 10px;
		padding: 5px 8px;
		border: 1px solid var(--border);
		border-radius: 7px;
	}

	.lines li.next {
		border-color: var(--gold);
		box-shadow: 0 0 6px var(--gold-glow);
	}

	.lines li.done {
		opacity: 0.8;
	}

	.stamp {
		font-family: var(--font-mono);
		font-size: 0.72rem;
		color: var(--gold);
		min-width: 3.2em;
	}

	.line-text {
		flex: 1;
	}

	.redo {
		padding: 2px 8px;
		font-size: 0.8rem;
	}
</style>
