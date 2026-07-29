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

	/* Phone: the grade bar pins to the bottom edge so every card can be graded
	   without scrolling — the 2x2 grid it replaced put Good/Easy below the fold.
	   Fixed rather than sticky: sticky only engages once content overflows, so
	   a short card left the bar floating mid-screen. The page pads its own
	   scroll area (see the practice route), so the bar never covers content.
	   Fine-pointer keycaps stay desktop-only: the digits are keyboard
	   mnemonics and only read as noise on touch. */
	@media (max-width: 700px) {
		.grades {
			position: fixed;
			left: 0;
			right: 0;
			bottom: 0;
			z-index: 40;
			margin: 0;
			padding: 10px 12px calc(10px + env(safe-area-inset-bottom, 0px));
			background: linear-gradient(transparent, var(--bg) 26%);
			gap: 8px;
		}

		.grade {
			flex-direction: row;
			justify-content: center;
			gap: 4px;
			min-height: 48px;
			padding: 12px 4px;
			background: var(--surface);
		}
	}

	/* Digit keycaps are keyboard mnemonics — meaningless on a touchscreen, so
	   only fine pointers (mouse/trackpad) see them. */
	@media (pointer: coarse) {
		.grade kbd {
			display: none;
		}
	}
</style>
