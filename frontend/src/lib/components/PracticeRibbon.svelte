<script lang="ts">
	import type { RibbonSpan } from '$lib/utils/ribbon';

	// One thin cell per line, in passage order. The gold span is the current
	// card's place in the poem; the dim trail is what this session has already
	// swept. Purely a "you are here" instrument — nothing here is tappable.
	let {
		total,
		span,
		dealt,
		labelFor
	}: {
		total: number;
		span: RibbonSpan | null;
		dealt: Set<number>;
		labelFor?: (position: number) => string;
	} = $props();

	const cells = $derived(
		Array.from({ length: total }, (_, index) => {
			const position = index + 1;
			const current = span !== null && position >= span.start && position <= span.end;
			return {
				position,
				current,
				seam: current && (span?.seam ?? false),
				swept: dealt.has(position)
			};
		})
	);
	const caption = $derived.by(() => {
		if (span === null) return '';
		const name = labelFor?.(span.start) ?? `line ${span.start}`;
		if (span.seam) return `crossing into ${name}`;
		if (span.end > span.start) {
			const last = labelFor?.(span.end) ?? `line ${span.end}`;
			return `${name} → ${last}`;
		}
		return name;
	});
</script>

{#if total > 1}
	<div class="ribbon" role="img" aria-label={caption ? `Position: ${caption}` : 'Position ribbon'}>
		<div class="track">
			{#each cells as cell (cell.position)}
				<span
					class="cell"
					class:current={cell.current}
					class:seam={cell.seam}
					class:swept={cell.swept}
				></span>
			{/each}
		</div>
		{#if caption}
			<span class="caption muted">{caption}</span>
		{/if}
	</div>
{/if}

<style>
	.ribbon {
		display: flex;
		align-items: center;
		gap: 10px;
		margin: 2px 0 10px;
	}

	.track {
		display: flex;
		flex: 1;
		gap: 2px;
	}

	.cell {
		flex: 1;
		height: 7px;
		border-radius: 3px;
		background: var(--surface-2);
		transition: background-color 200ms ease;
	}

	.cell.swept {
		background: color-mix(in srgb, var(--gold) 30%, var(--surface-2));
	}

	.cell.current {
		background: var(--gold);
	}

	/* A seam card crosses INTO its line: the leading edge carries the accent
	   so the boundary itself reads as the thing being practiced. */
	.cell.seam {
		background: linear-gradient(90deg, var(--gold), color-mix(in srgb, var(--gold) 35%, var(--surface-2)));
	}

	.caption {
		font-size: 0.72rem;
		white-space: nowrap;
	}

	@media (prefers-reduced-motion: reduce) {
		.cell {
			transition: none;
		}
	}
</style>
