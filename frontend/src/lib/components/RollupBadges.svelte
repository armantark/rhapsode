<script lang="ts">
	import type { CollectionRollup } from '$lib/api/types';

	let { rollup }: { rollup: CollectionRollup } = $props();

	// Anki's three queues, mutually exclusive by contract: never-reviewed (new),
	// in acquisition (learning), and graduated-but-due-now (due).
	const counts = $derived([
		{ label: 'new', value: rollup.new, klass: 'new' },
		{ label: 'learn', value: rollup.learning, klass: 'learn' },
		{ label: 'due', value: rollup.due, klass: 'due' }
	]);
</script>

<div class="rollup" role="group" aria-label="Review counts">
	{#each counts as count (count.label)}
		<span class="badge {count.klass}" class:zero={count.value === 0}>
			<strong>{count.value}</strong>
			{count.label}
		</span>
	{/each}
</div>

<style>
	.rollup {
		display: flex;
		gap: 8px;
		font-family: var(--font-mono);
		font-size: 0.72rem;
	}

	.badge {
		display: inline-flex;
		align-items: baseline;
		gap: 4px;
		padding: 2px 8px;
		border-radius: 999px;
		border: 1px solid var(--border);
	}

	.badge strong {
		font-size: 0.85rem;
	}

	.badge.new {
		color: var(--blue);
	}

	.badge.learn {
		color: var(--red);
	}

	.badge.due {
		color: var(--green);
	}

	.badge.zero {
		opacity: 0.45;
	}
</style>
