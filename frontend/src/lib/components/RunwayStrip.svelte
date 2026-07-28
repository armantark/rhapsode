<script lang="ts">
	import type { Segment } from '$lib/api/types';
	import { runwayStates } from '$lib/utils/runway';

	// `mastered` carries the planner's own gate (acquisition_succeeded with a
	// finished ladder), read from the same review states the reading gutter
	// uses, so the strip never disagrees with the planner or the dots.
	let {
		lines,
		mastered,
		windowSize
	}: { lines: Segment[]; mastered: Set<string>; windowSize: number } = $props();

	const cells = $derived(
		runwayStates(
			lines.map((line) => mastered.has(line.id)),
			windowSize
		).map((state, index) => ({
			id: lines[index].id,
			number: index + 1,
			text: lines[index].text,
			state
		}))
	);

	const firstActive = $derived(cells.find((cell) => cell.state === 'active'));
	const firstLocked = $derived(cells.find((cell) => cell.state === 'locked'));
	const masteredCount = $derived(cells.filter((cell) => cell.state === 'mastered').length);
</script>

<div class="runway">
	<div class="head">
		<span class="eyebrow">Runway</span>
		<span class="muted small">{masteredCount} of {cells.length} mastered</span>
	</div>
	<ol class="strip">
		{#each cells as cell (cell.id)}
			<li
				class="cell {cell.state}"
				data-testid="runway-cell"
				data-state={cell.state}
				aria-label="Line {cell.number}, {cell.state}"
				title={cell.text}
			>
				{cell.number}
				{#if cell.state !== 'active'}
					<span class="mark" aria-hidden="true">{cell.state === 'mastered' ? '✓' : '🔒'}</span>
				{/if}
			</li>
		{/each}
	</ol>
	<p class="muted small caption">
		{#if firstLocked && firstActive}
			Line {firstLocked.number} unlocks when line {firstActive.number} is mastered.
		{:else if firstActive}
			Nothing is locked ahead — every remaining line is in the window.
		{:else}
			Every line finished the ladder. The whole passage is in review now.
		{/if}
	</p>
</div>

<style>
	.runway {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 10px;
	}

	.small {
		font-size: 0.78rem;
	}

	.strip {
		display: flex;
		flex-wrap: wrap;
		gap: 5px;
		margin: 0;
		padding: 0;
		list-style: none;
		/* Long passages (hundreds of lines) scroll inside the card rather than
		   pushing the reading view off the screen. */
		max-height: 10.5rem;
		overflow-y: auto;
	}

	.cell {
		display: inline-flex;
		align-items: center;
		gap: 3px;
		min-width: 34px;
		justify-content: center;
		padding: 4px 6px;
		border: 1px solid var(--border);
		border-radius: 7px;
		background: var(--surface-2);
		font-family: var(--font-mono);
		font-size: 0.72rem;
		color: var(--text-dim);
		transition:
			background-color 240ms ease,
			border-color 240ms ease,
			color 240ms ease;
	}

	.cell.mastered {
		border-color: var(--green);
		color: var(--green);
		background: rgba(74, 222, 128, 0.1);
	}

	.cell.active {
		border-color: var(--gold);
		color: var(--gold);
		background: var(--gold-glow);
	}

	.cell.locked {
		opacity: 0.42;
	}

	.mark {
		font-size: 0.68rem;
		line-height: 1;
	}

	.caption {
		margin: 0;
	}

	@media (prefers-reduced-motion: reduce) {
		.cell {
			transition: none;
		}
	}
</style>
