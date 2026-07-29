import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import RunwayStrip from './RunwayStrip.svelte';
import type { Segment } from '$lib/api/types';

function lines(count: number): Segment[] {
	return Array.from({ length: count }, (_unused, index) => ({
		id: `line-${index + 1}`,
		revision_id: 'rev',
		parent_id: null,
		kind: 'line',
		ordinal: index,
		text: `line ${index + 1}`,
		cue: null,
		reference_label: null,
		metadata_json: {},
		annotations: []
	})) as Segment[];
}

function mount(count: number, onPractice = vi.fn()) {
	render(RunwayStrip, {
		lines: lines(count),
		mastered: new Set<string>(),
		windowSize: 3,
		onPractice
	});
	return { cells: screen.getAllByTestId('runway-cell'), onPractice };
}

describe('RunwayStrip range picker', () => {
	it('launches a scoped session from two taps, in either order', async () => {
		const { cells, onPractice } = mount(6);
		await fireEvent.click(cells[4]);
		await fireEvent.click(cells[1]);
		await fireEvent.click(screen.getByRole('button', { name: /Practice lines 2–5/ }));
		expect(onPractice).toHaveBeenCalledWith(2, 5);
	});

	it('offers a single line after the first tap', async () => {
		const { cells, onPractice } = mount(6);
		await fireEvent.click(cells[3]);
		await fireEvent.click(screen.getByRole('button', { name: /Practice line 4/ }));
		expect(onPractice).toHaveBeenCalledWith(4, 4);
	});

	it('keeps the runway state under the selection and clears it on demand', async () => {
		const { cells } = mount(6);
		await fireEvent.click(cells[3]);
		await fireEvent.click(cells[4]);
		// Locked lines stay locked-looking; selection is an overlay, and a
		// locked line is exactly what the picker exists to reach.
		expect(cells[4]).toHaveAttribute('data-state', 'locked');
		expect(cells[4]).toHaveAttribute('aria-pressed', 'true');
		expect(cells[2]).toHaveAttribute('aria-pressed', 'false');

		await fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
		expect(screen.queryByTestId('runway-range')).toBeNull();
		expect(cells[4]).toHaveAttribute('aria-pressed', 'false');
	});
});
