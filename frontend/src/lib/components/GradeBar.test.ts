import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import GradeBar from './GradeBar.svelte';

describe('GradeBar', () => {
	it('exposes the four contract ratings as buttons', () => {
		render(GradeBar, { onGrade: vi.fn() });
		for (const rating of ['clean', 'hesitant', 'incorrect', 'revealed']) {
			expect(screen.getByRole('button', { name: new RegExp(rating) })).toBeInTheDocument();
		}
	});

	it('grades via number-key shortcuts', async () => {
		const onGrade = vi.fn();
		render(GradeBar, { onGrade });
		await fireEvent.keyDown(window, { key: '2' });
		expect(onGrade).toHaveBeenCalledWith('hesitant');
		await fireEvent.keyDown(window, { key: '4' });
		expect(onGrade).toHaveBeenCalledWith('revealed');
	});

	it('ignores shortcuts while typing in a form field', async () => {
		const onGrade = vi.fn();
		render(GradeBar, { onGrade });
		const input = document.createElement('input');
		document.body.append(input);
		input.focus();
		await fireEvent.keyDown(input, { key: '1' });
		expect(onGrade).not.toHaveBeenCalled();
		input.remove();
	});

	it('blocks grading while a submission is in flight', async () => {
		const onGrade = vi.fn();
		render(GradeBar, { onGrade, disabled: true });
		await fireEvent.keyDown(window, { key: '1' });
		expect(onGrade).not.toHaveBeenCalled();
		// jsdom dispatches clicks on disabled buttons, so assert the attribute
		// browsers actually honor.
		expect(screen.getByRole('button', { name: /clean/ })).toBeDisabled();
	});
});
