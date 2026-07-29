<script lang="ts">
	import type { Segment } from '$lib/api/types';
	import { runwayStates, selectLine, selectedRange, type LineSelection } from '$lib/utils/runway';

	// `mastered` carries the planner's own gate (acquisition_succeeded with a
	// finished ladder), read from the same review states the reading gutter
	// uses, so the strip never disagrees with the planner or the dots.
	let {
		lines,
		mastered,
		windowSize,
		onPractice,
		launching = false
	}: {
		lines: Segment[];
		mastered: Set<string>;
		windowSize: number;
		onPractice?: (start: number, end: number) => void;
		launching?: boolean;
	} = $props();

	// The strip doubles as a range picker: the runway is the passage's default
	// order, and a picked range is the owner overriding it on purpose. The
	// selection is an overlay on the mastered/active/locked states, never a
	// replacement, so the runway stays readable while choosing.
	let selection: LineSelection | null = $state(null);
	const range = $derived(selectedRange(selection));

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
	const rangeLabel = $derived(
		range === null
			? ''
			: range.start === range.end
				? `line ${range.start}`
				: `lines ${range.start}–${range.end}`
	);
</script>

<div class="runway">
	<div class="head">
		<span class="eyebrow">Runway</span>
		<span class="muted small">{masteredCount} of {cells.length} mastered</span>
	</div>
	<ol class="strip">
		{#each cells as cell (cell.id)}
			{@const picked = range !== null && cell.number >= range.start && cell.number <= range.end}
			<li>
				<button
					class="cell {cell.state}"
					class:picked
					class:edge={picked && (cell.number === range?.start || cell.number === range?.end)}
					data-testid="runway-cell"
					data-state={cell.state}
					aria-pressed={picked}
					aria-label="Line {cell.number}, {cell.state}"
					title={cell.text}
					onclick={() => (selection = selectLine(selection, cell.number))}
				>
					{cell.number}
					{#if cell.state !== 'active'}
						<span class="mark" aria-hidden="true">{cell.state === 'mastered' ? '✓' : '🔒'}</span>
					{/if}
				</button>
			</li>
		{/each}
	</ol>
	{#if range !== null}
		<div class="picker" data-testid="runway-range">
			<button
				class="primary"
				disabled={launching}
				onclick={() => onPractice?.(range.start, range.end)}
			>
				{launching ? 'Starting…' : `✦ Practice ${rangeLabel}`}
			</button>
			<button class="clear" onclick={() => (selection = null)}>Clear</button>
			<p class="muted small">
				{#if selection?.end === null}
					Tap another line to extend the range, or start here.
				{:else}
					This session drills {rangeLabel} only, whatever the runway has unlocked.
				{/if}
			</p>
		</div>
	{:else}
		<p class="muted small caption">
			{#if firstLocked && firstActive}
				Line {firstLocked.number} unlocks when line {firstActive.number} is mastered.
			{:else if firstActive}
				Nothing is locked ahead — every remaining line is in the window.
			{:else}
				Every line finished the ladder. The whole passage is in review now.
			{/if}
			Tap two lines to practice that range instead.
		</p>
	{/if}
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
		max-height: 12.5rem;
		overflow-y: auto;
	}

	.cell {
		display: inline-flex;
		align-items: center;
		gap: 3px;
		/* A thumb-sized target: the strip is the primary way to scope a
		   session on a phone, so cells are tappable, not just readable. */
		min-width: 44px;
		min-height: 44px;
		justify-content: center;
		padding: 4px 6px;
		border: 1px solid var(--border);
		border-radius: 7px;
		background: var(--surface-2);
		font-family: var(--font-mono);
		font-size: 0.72rem;
		color: var(--text-dim);
		cursor: pointer;
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

	/* Selection rides on top of the runway state: the ladder colours stay, an
	   outline and a lift mark the picked span. A picked locked line is shown
	   at full strength — choosing it is the whole point of the override. */
	.cell.picked {
		outline: 2px solid var(--purple);
		outline-offset: -2px;
		opacity: 1;
	}

	.cell.edge {
		outline-width: 3px;
	}

	.picker {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 8px;
	}

	.picker p {
		flex-basis: 100%;
		margin: 0;
	}

	.picker button {
		min-height: 44px;
	}

	.clear {
		background: none;
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
