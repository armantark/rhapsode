<script lang="ts">
	/** Shimmering placeholder rows shown while a page loads — steadier than a
	 *  bare "Loading…" string and it sketches the shape of what's coming. */
	let { rows = 3, card = false }: { rows?: number; card?: boolean } = $props();
</script>

<div class="skeleton" class:card aria-hidden="true">
	{#each Array(rows) as _, index (index)}
		<div class="bar" style:width="{88 - index * 9}%"></div>
	{/each}
</div>

<style>
	.skeleton {
		display: flex;
		flex-direction: column;
		gap: 12px;
		padding: 4px 0;
	}

	.skeleton.card {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: 18px 20px;
	}

	.bar {
		height: 13px;
		border-radius: 6px;
		background: linear-gradient(
			100deg,
			var(--surface-2) 40%,
			#262d3a 50%,
			var(--surface-2) 60%
		);
		background-size: 200% 100%;
		animation: shimmer 1.4s ease-in-out infinite;
	}

	@keyframes shimmer {
		0% {
			background-position: 120% 0;
		}
		100% {
			background-position: -80% 0;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.bar {
			animation: none;
		}
	}
</style>
