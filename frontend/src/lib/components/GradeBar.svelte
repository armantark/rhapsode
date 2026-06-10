<script lang="ts">
	import type { AttemptRating } from '$lib/api/types';

	let {
		onGrade,
		disabled = false
	}: {
		onGrade: (rating: AttemptRating) => void;
		disabled?: boolean;
	} = $props();

	const GRADES: { rating: AttemptRating; key: string; label: string; hint: string }[] = [
		{ rating: 'revealed', key: '1', label: 'Again', hint: 'Needed the text' },
		{ rating: 'incorrect', key: '2', label: 'Hard', hint: 'Errors in recall' },
		{ rating: 'hesitant', key: '3', label: 'Good', hint: 'Recalled with pauses' },
		{ rating: 'clean', key: '4', label: 'Easy', hint: 'Perfect recall' }
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
			<span>{grade.label}</span>
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
