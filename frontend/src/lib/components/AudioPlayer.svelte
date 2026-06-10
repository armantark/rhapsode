<script lang="ts">
	import type { CuePoint } from '$lib/api/types';

	let {
		src,
		title = 'Audio',
		storageKey = null,
		cuePoints = [],
		focusSegmentId = null
	}: {
		src: string;
		title?: string;
		/** When set, ad-hoc cue points persist in localStorage under this key. */
		storageKey?: string | null;
		/** Server-side cue points (e.g. from pause-based line alignment). When a
		 *  cue carries an `end`, jumping to it loops just that line's span. */
		cuePoints?: CuePoint[];
		/** During shadowing, the segment being practised: if a server cue matches
		 *  it, the player jumps there and loops the line automatically. */
		focusSegmentId?: string | null;
	} = $props();

	let audio: HTMLAudioElement | undefined = $state();
	let currentTime = $state(0);
	let duration = $state(0);
	let paused = $state(true);
	let playbackRate = $state(1);
	let loopStart: number | null = $state(null);
	let loopEnd: number | null = $state(null);
	let looping = $state(false);
	let cues: { label: string; time: number }[] = $state(loadCues());

	const SPEEDS = [0.5, 0.65, 0.8, 0.9, 1, 1.1, 1.25, 1.5];

	function loadCues(): { label: string; time: number }[] {
		if (!storageKey) return [];
		try {
			return JSON.parse(localStorage.getItem(`rhapsode.cues.${storageKey}`) ?? '[]');
		} catch {
			return [];
		}
	}

	function persistCues() {
		if (storageKey) localStorage.setItem(`rhapsode.cues.${storageKey}`, JSON.stringify(cues));
	}

	function format(seconds: number): string {
		if (!Number.isFinite(seconds)) return '0:00';
		const m = Math.floor(seconds / 60);
		const s = Math.floor(seconds % 60);
		return `${m}:${s.toString().padStart(2, '0')}`;
	}

	function onTimeUpdate() {
		currentTime = audio?.currentTime ?? 0;
		if (looping && loopStart !== null && loopEnd !== null && currentTime >= loopEnd && audio) {
			audio.currentTime = loopStart;
		}
	}

	function toggle() {
		if (!audio) return;
		if (audio.paused) void audio.play();
		else audio.pause();
	}

	function seek(time: number) {
		if (audio) audio.currentTime = Math.min(Math.max(time, 0), duration || time);
	}

	function setRate(rate: number) {
		playbackRate = rate;
		if (audio) audio.playbackRate = rate;
	}

	function markLoop(which: 'start' | 'end') {
		if (which === 'start') loopStart = currentTime;
		else loopEnd = currentTime;
		if (loopStart !== null && loopEnd !== null && loopEnd <= loopStart) {
			[loopStart, loopEnd] = [Math.min(loopStart, loopEnd), Math.max(loopStart, loopEnd)];
		}
		if (loopStart !== null && loopEnd !== null) looping = true;
	}

	function clearLoop() {
		loopStart = loopEnd = null;
		looping = false;
	}

	function addCue() {
		cues = [...cues, { label: `cue ${cues.length + 1}`, time: currentTime }].sort(
			(a, b) => a.time - b.time
		);
		persistCues();
	}

	function removeCue(index: number) {
		cues = cues.toSpliced(index, 1);
		persistCues();
	}

	function jumpToCue(cue: CuePoint) {
		seek(cue.time);
		if (cue.end != null) {
			loopStart = cue.time;
			loopEnd = cue.end;
			looping = true;
		}
		void audio?.play();
	}

	const focusCue = $derived.by(() =>
		focusSegmentId ? (cuePoints.find((cue) => cue.segment_id === focusSegmentId) ?? null) : null
	);

	$effect(() => {
		// When the practised line changes (or the audio finishes loading), cue the
		// player to that line's span so shadowing starts in the right place.
		const cue = focusCue;
		if (!cue || !audio) return;
		const apply = () => {
			seek(cue.time);
			if (cue.end != null) {
				loopStart = cue.time;
				loopEnd = cue.end;
				looping = true;
			}
		};
		if (duration) apply();
		else audio.addEventListener('loadedmetadata', apply, { once: true });
	});
</script>

<div class="player card">
	<div class="row top">
		<span class="eyebrow">{title}</span>
		<span class="time muted">{format(currentTime)} / {format(duration)}</span>
	</div>

	<audio
		bind:this={audio}
		{src}
		preload="metadata"
		ontimeupdate={onTimeUpdate}
		ondurationchange={() => (duration = audio?.duration ?? 0)}
		onloadedmetadata={() => (duration = audio?.duration ?? 0)}
		onplay={() => (paused = false)}
		onpause={() => (paused = true)}
	></audio>

	<input
		class="scrub"
		type="range"
		min="0"
		max={duration || 1}
		step="0.05"
		value={currentTime}
		aria-label="Seek"
		oninput={(event) => seek(Number(event.currentTarget.value))}
	/>

	<div class="row controls">
		<button class="primary" onclick={toggle} aria-label={paused ? 'Play' : 'Pause'}>
			{paused ? '▶ Play' : '⏸ Pause'}
		</button>
		<button onclick={() => markLoop('start')} title="Set loop start at playhead">A</button>
		<button onclick={() => markLoop('end')} title="Set loop end at playhead">B</button>
		<button
			class:active={looping}
			disabled={loopStart === null || loopEnd === null}
			onclick={() => (looping = !looping)}
			aria-pressed={looping}
		>
			Loop {loopStart !== null ? format(loopStart) : '–'}–{loopEnd !== null ? format(loopEnd) : '–'}
		</button>
		{#if loopStart !== null || loopEnd !== null}
			<button onclick={clearLoop}>Clear</button>
		{/if}
		<label class="speed">
			<span class="muted">Speed</span>
			<select value={playbackRate} onchange={(event) => setRate(Number(event.currentTarget.value))}>
				{#each SPEEDS as speed (speed)}
					<option value={speed}>{speed}×</option>
				{/each}
			</select>
		</label>
	</div>

	{#if cuePoints.length}
		<div class="row cues lines">
			<span class="muted small">Lines</span>
			{#each cuePoints as cue (cue.time)}
				<button
					class="cue-jump line"
					class:focused={focusCue?.time === cue.time}
					onclick={() => jumpToCue(cue)}
				>
					{cue.label}
				</button>
			{/each}
		</div>
	{/if}

	<div class="row cues">
		<button onclick={addCue}>+ Cue at {format(currentTime)}</button>
		{#each cues as cue, index (cue.time)}
			<span class="cue-chip">
				<button class="cue-jump" onclick={() => seek(cue.time)}>{cue.label} · {format(cue.time)}</button>
				<button class="cue-remove" aria-label="Remove {cue.label}" onclick={() => removeCue(index)}>×</button>
			</span>
		{/each}
	</div>
</div>

<style>
	.player {
		display: flex;
		flex-direction: column;
		gap: 10px;
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

	.scrub {
		width: 100%;
		accent-color: var(--gold);
		padding: 0;
	}

	.speed {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-inline-start: auto;
		margin-bottom: 0;
	}

	.speed select {
		width: auto;
	}

	button.active {
		border-color: var(--gold);
		color: var(--gold);
	}

	.cue-chip {
		display: inline-flex;
		align-items: center;
	}

	.cue-jump {
		border-start-end-radius: 0;
		border-end-end-radius: 0;
		font-family: var(--font-mono);
		font-size: 0.72rem;
	}

	.cue-remove {
		border-start-start-radius: 0;
		border-end-start-radius: 0;
		border-inline-start: none;
		padding: 8px 9px;
	}

	.cues.lines {
		gap: 6px;
	}

	.small {
		font-size: 0.72rem;
	}

	.cue-jump.line {
		border-radius: 6px;
		font-size: 0.72rem;
	}

	.cue-jump.line.focused {
		border-color: var(--gold);
		color: var(--gold);
		box-shadow: 0 0 6px var(--gold-glow);
	}
</style>
