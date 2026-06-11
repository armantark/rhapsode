import { expect, test, type Page } from '@playwright/test';

const GREEK_LINE = 'μῆνιν ἄειδε θεὰ Πηληϊάδεω Ἀχιλῆος';

async function createCuedPassage(page: Page, title: string): Promise<void> {
	await page.goto('/passages/new');
	await page.getByLabel('Title').fill(title);
	await page.getByLabel('Language').selectOption({ label: 'Ancient Greek' });
	await page.getByLabel(/Source text/).fill(GREEK_LINE);
	await page.getByRole('button', { name: 'Generate line segments' }).click();
	await page.getByPlaceholder('recall cue').first().fill('Sing, goddess');
	await page.getByRole('button', { name: 'Create passage' }).click();
	await expect(page).toHaveURL(/\/passages\/[\w-]+/);
}

async function startManualSession(page: Page): Promise<void> {
	await page.getByText('Choose modes manually').click();
	await page.getByRole('button', { name: '▶ Start manual session' }).click();
	await expect(page).toHaveURL(/\/practice\/[\w-]+/);
}

test('a personal note overrides the drafted hint and survives a reload', async ({ page }) => {
	const title = `Notes e2e ${Date.now()}`;
	await createCuedPassage(page, title);
	await startManualSession(page);

	// The drafted cue is the fallback hint, kept behind the reveal.
	await page.getByRole('button', { name: /Need a hint/ }).click();
	await expect(page.getByText('Sing, goddess')).toBeVisible();

	// Author a personal mnemonic; it replaces the drafted hint on the card.
	await page.getByRole('button', { name: /Add a note/ }).click();
	await page.getByLabel('Personal note').fill('mēnin ~ "mean": Achilles is mean');
	await page.getByRole('button', { name: 'Save note' }).click();

	await expect(page.getByText('mēnin ~ "mean": Achilles is mean')).toBeVisible();
	await expect(page.getByText('your note')).toBeVisible();
	await expect(page.getByText('Sing, goddess')).toBeHidden();

	// The note is durable: a reload re-fetches it live (not from the frozen
	// session prompt) and shows it again behind the reveal.
	await page.reload();
	await page.getByRole('button', { name: /Need a hint/ }).click();
	await expect(page.getByText('mēnin ~ "mean": Achilles is mean')).toBeVisible();

	// Editing updates in place without recreating the session.
	await page.getByRole('button', { name: 'Edit note' }).click();
	await page.getByLabel('Personal note').fill('updated hook');
	await page.getByRole('button', { name: 'Save note' }).click();
	await expect(page.getByText('updated hook')).toBeVisible();
});
