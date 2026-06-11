import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import RollupBadges from './RollupBadges.svelte';

describe('RollupBadges', () => {
	it('renders the three mutually exclusive queue counts', () => {
		render(RollupBadges, { rollup: { due: 8, learning: 3, new: 12 } });
		expect(screen.getByText('new').closest('.badge')?.textContent).toContain('12');
		expect(screen.getByText('learn').closest('.badge')?.textContent).toContain('3');
		expect(screen.getByText('due').closest('.badge')?.textContent).toContain('8');
	});

	it('dims a queue that is empty so the eye skips it', () => {
		render(RollupBadges, { rollup: { due: 0, learning: 0, new: 5 } });
		expect(screen.getByText('due').closest('.badge')?.className).toContain('zero');
		expect(screen.getByText('new').closest('.badge')?.className).not.toContain('zero');
	});
});
