import { expect, test, type Page } from '@playwright/test';

const LINES = [
	'μῆνιν ἄειδε θεὰ Πηληϊάδεω Ἀχιλῆος',
	'οὐλομένην, ἣ μυρί᾽ Ἀχαιοῖς ἄλγε᾽ ἔθηκε'
];

async function createSingleLinePassage(page: Page, title: string, line: string): Promise<void> {
	await page.goto('/passages/new');
	await page.getByLabel('Title').fill(title);
	await page.getByLabel('Language').selectOption({ label: 'Ancient Greek' });
	await page.getByLabel(/Source text/).fill(line);
	await page.getByRole('button', { name: 'Generate line segments' }).click();
	await page.getByRole('button', { name: 'Create passage' }).click();
	await expect(page).toHaveURL(/\/passages\/[\w-]+/);
}

async function completeAcquisition(page: Page): Promise<void> {
	// Two phases: encounter → supported reconstruction; the visible check
	// unlocks grading (production waits for the line's next, spaced visit).
	await page.getByRole('button', { name: /I’ve read it/ }).click();
	while ((await page.locator('.bank-pool .chip').count()) > 0) {
		await page.locator('.bank-pool .chip').first().click();
	}
	await page.getByRole('button', { name: 'Check reconstruction' }).click();
	await page.getByText('true line').waitFor();
}

test('group two passages into a collection, reorder, and practice the whole arc', async ({
	page
}) => {
	const stamp = Date.now();
	const titleA = `Arc A ${stamp}`;
	const titleB = `Arc B ${stamp}`;
	await createSingleLinePassage(page, titleA, LINES[0]);
	await createSingleLinePassage(page, titleB, LINES[1]);

	// Create the collection.
	await page.goto('/collections');
	await page.getByLabel('New collection name').fill(`Iliad arc ${stamp}`);
	await page.getByRole('button', { name: /New collection/ }).click();
	await page.getByRole('link', { name: `Iliad arc ${stamp}` }).click();
	await expect(page).toHaveURL(/\/collections\/[\w-]+/);

	// Add both passages, in order A then B.
	await page.getByLabel('Add a passage').selectOption({ label: titleA });
	await page.getByRole('button', { name: '+ Add' }).click();
	await page.getByLabel('Add a passage').selectOption({ label: titleB });
	await page.getByRole('button', { name: '+ Add' }).click();

	const items = page.locator('.members li');
	await expect(items).toHaveCount(2);
	await expect(items.nth(0)).toContainText(titleA);
	await expect(items.nth(1)).toContainText(titleB);

	// Rollup: two never-practiced lines → two "new".
	await expect(page.locator('.badge.new')).toContainText('2');

	// Reorder: move B up; the order flips, then move it back.
	await items.nth(1).getByRole('button', { name: 'Move up' }).click();
	await expect(page.locator('.members li').nth(0)).toContainText(titleB);
	await page.locator('.members li').nth(0).getByRole('button', { name: 'Move down' }).click();
	await expect(page.locator('.members li').nth(0)).toContainText(titleA);

	// Launch a smart session over the whole collection.
	await page.getByRole('button', { name: '✦ Smart session' }).click();
	await expect(page).toHaveURL(/\/practice\/[\w-]+/);

	// The session is collection-scoped: header names the collection, and there
	// is one item per member line.
	await expect(page.getByText('Collection practice')).toBeVisible();
	await expect(page.getByRole('heading', { name: `Iliad arc ${stamp}` })).toBeVisible();
	await expect(page.getByText('0/2 items')).toBeVisible();

	// Each card carries its own passage context (subtitle switches per item).
	await expect(page.locator('.head-sub')).toContainText(titleA);
	await completeAcquisition(page);
	await page.keyboard.press('4');
	await expect(page.getByText('1/2 items')).toBeVisible();
	await expect(page.locator('.head-sub')).toContainText(titleB);
	await completeAcquisition(page);
	await page.keyboard.press('4');
	await expect(page.getByText('Session complete')).toBeVisible();

	// The session appears in the practice list tagged as a collection.
	await page.goto('/practice');
	await expect(page.getByText(`Iliad arc ${stamp}`)).toBeVisible();
	await expect(page.locator('.session .tag.collection').first()).toBeVisible();
});

test('removing a passage from a collection leaves the passage intact', async ({ page }) => {
	const stamp = Date.now();
	const title = `Solo ${stamp}`;
	await createSingleLinePassage(page, title, LINES[0]);

	await page.goto('/collections');
	await page.getByLabel('New collection name').fill(`Removable ${stamp}`);
	await page.getByRole('button', { name: /New collection/ }).click();
	await page.getByRole('link', { name: `Removable ${stamp}` }).click();

	await page.getByLabel('Add a passage').selectOption({ label: title });
	await page.getByRole('button', { name: '+ Add' }).click();
	await expect(page.locator('.members li')).toHaveCount(1);

	await page.getByRole('button', { name: 'Remove' }).click();
	await expect(page.locator('.members li')).toHaveCount(0);

	// The passage itself still exists in the library.
	await page.goto('/');
	await expect(page.getByRole('heading', { name: title })).toBeVisible();
});
