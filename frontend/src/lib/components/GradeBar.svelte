<script lang="ts">
	import type { AttemptRating } from '$lib/api/types';

	let {
		onGrade,
		disabled = false
	}: {
		onGrade: (rating: AttemptRating) => void;
		disabled?: boolean;
	} = $props();

	const GRADES: { rating: AttemptRating; key: string; hint: string }[] = [
		{ rating: 'clean', key: '1', hint: 'Perfect recall' },
		{ rating: 'hesitant', key: '2', hint: 'Recalled with pauses' },
		{ rating: 'incorrect', key: '3', hint: 'Errors in recall' },
		{ rating: 'revealed', key: '4', hint: 'Needed the text' }
	];

	function onKeydown(event: KeyboardEvent) {
		if (disabled) return;
		const target = event.target as HTMLElement | null;
		if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
		const grade = GRADES.find((candidate) => candidate.key === event.key);
		if (grade) {
			event.preventDefault();
			onGrade(grade.rating);
		}
	}
</script>

<svelte:window onkeydown={onKeydown} />

<div class="grades" role="group" aria-label="Self-grade this attempt">
	{#each GRADES as grade (grade.rating)}
		<button class="grade {grade.rating}" {disabled} title={grade.hint} onclick={() => onGrade(grade.rating)}>
			<kbd>{grade.key}</kbd>
			<span>{grade.rating}</span>
		</button>
	{/each}
</div>

<style>
	.grades {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 10px;
	}

	.grade {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 6px;
		padding: 14px 8px;
		text-transform: capitalize;
		font-weight: 600;
	}

	.grade.clean { color: var(--green); border-color: var(--green); }
	.grade.hesitant { color: var(--gold); border-color: var(--gold); }
	.grade.incorrect { color: var(--red); border-color: var(--red); }
	.grade.revealed { color: var(--purple); border-color: var(--purple); }

	@media (max-width: 700px) {
		.grades { grid-template-columns: repeat(2, 1fr); }
	}
</style>
