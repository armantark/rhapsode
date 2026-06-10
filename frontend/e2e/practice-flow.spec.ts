import { expect, test, type Page } from '@playwright/test';

const GREEK_LINE_1 = 'μῆνιν ἄειδε θεὰ Πηληϊάδεω Ἀχιλῆος';
const GREEK_LINE_2 = 'οὐλομένην, ἣ μυρί᾽ Ἀχαιοῖς ἄλγε᾽ ἔθηκε';

async function createGreekPassage(page: Page, title: string): Promise<void> {
	await page.goto('/passages/new');
	await page.getByLabel('Title').fill(title);
	await page.getByLabel('Language').selectOption({ label: 'Ancient Greek' });
	await page.getByLabel('Description').fill('Opening invocation');
	await page.getByLabel(/Source text/).fill(`${GREEK_LINE_1}\n${GREEK_LINE_2}`);
	await page.getByRole('button', { name: 'Generate line segments' }).click();
	await page.getByPlaceholder('recall cue').first().fill('Sing, goddess');
	await page.getByRole('button', { name: 'Create passage' }).click();
	await expect(page).toHaveURL(/\/passages\/[\w-]+/);
}

test('full loop: create, render Unicode, practice, grade, review', async ({ page }) => {
	const title = `Iliad e2e ${Date.now()}`;
	await createGreekPassage(page, title);

	// Polytonic Greek renders intact with line+token structure from the editor.
	await expect(page.getByText(GREEK_LINE_1).first()).toBeVisible();
	await expect(page.getByText(GREEK_LINE_2).first()).toBeVisible();

	// cue_recall over line segments is the launcher default.
	await page.getByRole('button', { name: '▶ Start session' }).click();
	await expect(page).toHaveURL(/\/practice\/[\w-]+/);

	// Item 1: grade clean via keyboard shortcut.
	await expect(page.getByText('Sing, goddess')).toBeVisible();
	await page.keyboard.press('1');
	await expect(page.getByText(/clean · mastery/)).toBeVisible();

	// Item 2: revealing forces the "revealed" rating regardless of the key.
	await page.getByRole('button', { name: /Reveal text/ }).click();
	await expect(page.getByText(GREEK_LINE_2).first()).toBeVisible();
	await page.keyboard.press('1');

	// Both items done → completion summary with the local tally.
	await expect(page.getByText('Session complete')).toBeVisible();
	await expect(page.getByText('clean × 1')).toBeVisible();
	await expect(page.getByText('revealed × 1')).toBeVisible();

	// Review analytics reflect the attempts.
	await page.goto('/review');
	await page.getByRole('tab', { name: 'Mastery' }).click();
	await expect(page.getByText(GREEK_LINE_1).first()).toBeVisible();
	await page.getByRole('tab', { name: 'Weak links' }).click();
	await expect(page.getByText(GREEK_LINE_2).first()).toBeVisible();
});

test('an interrupted session resumes at the persisted cursor after reload', async ({ page }) => {
	const title = `Recovery e2e ${Date.now()}`;
	await createGreekPassage(page, title);
	await page.getByRole('button', { name: '▶ Start session' }).click();
	await expect(page).toHaveURL(/\/practice\/[\w-]+/);
	const sessionUrl = page.url();

	await expect(page.getByText('Sing, goddess')).toBeVisible();
	await page.keyboard.press('2'); // hesitant on item 1
	await expect(page.getByText(/hesitant · mastery/)).toBeVisible();

	// Simulate a crash: hard reload, then verify the same item cursor.
	await page.reload();
	await expect(page.getByText('1/2 items')).toBeVisible();
	await expect(page.getByRole('button', { name: /Reveal text/ })).toBeVisible();

	// The practice list also offers recovery from the localStorage pointer.
	await page.goto('/practice');
	const resumeBanner = page.getByRole('link', { name: /where you left off/ });
	await expect(resumeBanner).toBeVisible();
	await resumeBanner.click();
	await expect(page).toHaveURL(sessionUrl);
	await expect(page.getByText('1/2 items')).toBeVisible();
});

test('recordings stay browser-local until explicitly saved as best', async ({ page }) => {
	const title = `Recording e2e ${Date.now()}`;
	await createGreekPassage(page, title);
	await page.getByRole('button', { name: '▶ Start session' }).click();

	const uploads: string[] = [];
	page.on('request', (request) => {
		if (request.url().includes('/api/v1/media') && request.method() === 'POST') {
			uploads.push(request.url());
		}
	});

	// Take one: record and discard — nothing may leave the browser.
	await page.getByRole('button', { name: '● Record' }).click();
	await page.waitForTimeout(600);
	await page.getByRole('button', { name: '■ Stop' }).click();
	await expect(page.locator('audio[aria-label="Play back your attempt"]')).toBeVisible();
	await page.getByRole('button', { name: 'Discard' }).click();
	expect(uploads).toHaveLength(0);

	// Take two: explicit save-best uploads exactly once.
	await page.getByRole('button', { name: '● Record' }).click();
	await page.waitForTimeout(600);
	await page.getByRole('button', { name: '■ Stop' }).click();
	await page.getByRole('button', { name: '★ Save as best' }).click();
	await expect(page.getByRole('button', { name: '✓ Saved best' })).toBeVisible();
	expect(uploads).toHaveLength(1);

	// The saved take is listed (and playable) under Review → Saved best.
	await page.goto('/review');
	await page.getByRole('tab', { name: 'Saved best' }).click();
	await expect(page.getByText(GREEK_LINE_1).first()).toBeVisible();
	await expect(page.getByRole('button', { name: 'Delete recording' })).toBeVisible();
});
