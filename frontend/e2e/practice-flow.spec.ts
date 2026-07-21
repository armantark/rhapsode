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
	await expect(page).toHaveURL(/\/passages\/(?!new(?:$|\/))[\w-]+$/);
	await expect(page.getByRole('heading', { name: title })).toBeVisible();
}

async function createSingleLinePassage(page: Page, title: string): Promise<void> {
	await page.goto('/passages/new');
	await page.getByLabel('Title').fill(title);
	await page.getByLabel('Language').selectOption({ label: 'Ancient Greek' });
	await page.getByLabel(/Source text/).fill(GREEK_LINE_1);
	await page.getByRole('button', { name: 'Generate line segments' }).click();
	await page.getByRole('button', { name: 'Create passage' }).click();
	await expect(page).toHaveURL(/\/passages\/(?!new(?:$|\/))[\w-]+$/);
	await expect(page.getByRole('heading', { name: title })).toBeVisible();
}

/** Manual mode selection lives behind a disclosure now that smart is the default. */
async function startManualSession(page: Page): Promise<void> {
	await page.getByText('Choose modes manually').click();
	await page.getByRole('button', { name: '▶ Start manual session' }).click();
}

async function completeAcquisition(page: Page): Promise<void> {
	// Two phases only: encounter, then supported reconstruction. Bare-cue
	// production is deferred to the line's next, spaced visit; the visible
	// true-line comparison is the self-check that unlocks grading.
	await expect(page.getByText('1 · encounter')).toBeVisible();
	await page.getByRole('button', { name: /I’ve read it/ }).click();
	await expect(page.getByText('2 · rebuild')).toBeVisible();
	while ((await page.locator('.bank-pool .chip').count()) > 0) {
		await page.locator('.bank-pool .chip').first().click();
	}
	await page.getByRole('button', { name: 'Check reconstruction' }).click();
	await expect(page.getByText('true line')).toBeVisible();
}

test('full loop: create, render Unicode, practice, grade, review', async ({ page }) => {
	const title = `Iliad e2e ${Date.now()}`;
	await createGreekPassage(page, title);

	// Polytonic Greek renders intact with line+token structure from the editor.
	await expect(page.getByText(GREEK_LINE_1).first()).toBeVisible();
	await expect(page.getByText(GREEK_LINE_2).first()).toBeVisible();

	// cue_recall over line segments is the launcher default.
	await startManualSession(page);
	await expect(page).toHaveURL(/\/practice\/[\w-]+/);

	// Item 1: the cue card shows the verbatim lead-in (the literal recall cue
	// now lives behind "Need a hint?"). Recall cards require the check before
	// grading, so Space flips the card first; then grade via "Easy" (4).
	await expect(page.getByText('Recite this line to the end.')).toBeVisible();
	await page.keyboard.press(' ');
	await page.keyboard.press('4');
	await expect(page.getByText(/Easy · mastery/)).toBeVisible();

	// Item 2: showing the answer is a neutral self-check (Anki model); the grade
	// is whatever the learner presses. Here we needed the text, so "Again" (1).
	await page.getByRole('button', { name: /Show answer/ }).click();
	await expect(page.getByText(GREEK_LINE_2).first()).toBeVisible();
	await expect(page.getByText(/grade yourself honestly/)).toBeVisible();
	await page.keyboard.press('1');

	// Both items done → completion summary with the local tally (Anki labels).
	await expect(page.getByText('Session complete')).toBeVisible();
	await expect(page.getByText('Easy × 1')).toBeVisible();
	await expect(page.getByText('Again × 1')).toBeVisible();

	// Review analytics reflect the attempts.
	await page.goto('/review');
	await page.getByRole('tab', { name: 'Mastery' }).click();
	await expect(page.getByText(GREEK_LINE_1).first()).toBeVisible();
	await page.getByRole('tab', { name: 'Weak links' }).click();
	await expect(page.getByText(GREEK_LINE_2).first()).toBeVisible();
});

test('manual random start does not begin at the first line', async ({ page }) => {
	const title = `Random start e2e ${Date.now()}`;
	await createGreekPassage(page, title);

	await page.getByText('Choose modes manually').click();
	await page.getByRole('button', { name: 'cue recall' }).click();
	await page.getByRole('button', { name: 'random start' }).click();
	await page.getByRole('button', { name: '▶ Start manual session' }).click();
	await expect(page).toHaveURL(/\/practice\/[\w-]+/);
	await expect(page.getByText('0/2 items')).toBeVisible();
	await expect(page.getByText('random start', { exact: true })).toBeVisible();

	await page.getByRole('button', { name: /Show answer/ }).click();
	await expect(page.getByText(GREEK_LINE_2).first()).toBeVisible();
});

test('source references identify chaining lines without passage-local ambiguity', async ({ page }) => {
	const title = `Source refs e2e ${Date.now()}`;
	await page.goto('/passages/new');
	await page.getByLabel('Title').fill(title);
	await page.getByLabel('Language').selectOption({ label: 'Ancient Greek' });
	await page.getByLabel('Source reference for this passage').fill('Iliad 1.6–7');
	await page.getByLabel(/Source text/).fill(`${GREEK_LINE_1}\n${GREEK_LINE_2}`);
	await page.getByRole('button', { name: 'Generate line segments' }).click();
	await page.getByLabel('Source reference', { exact: true }).nth(0).fill('Iliad 1.6');
	await page.getByLabel('Source reference', { exact: true }).nth(1).fill('Iliad 1.7');
	await page.getByRole('button', { name: 'Create passage' }).click();

	await page.getByText('Choose modes manually').click();
	await page.getByRole('button', { name: 'cue recall' }).click();
	await page.getByRole('button', { name: 'forward chaining' }).click();
	await page.getByRole('button', { name: '▶ Start manual session' }).click();

	await expect(page.getByText('From memory, recite Iliad 1.6, then check.')).toBeVisible();
	await expect(page.getByText('Recite Iliad 1.6 from memory.')).toBeVisible();
	await page.getByRole('button', { name: /Show answer/ }).click();
	await expect(page.locator('.chain-reference')).toHaveText('Iliad 1.6');
});

test('an interrupted session resumes at the persisted cursor after reload', async ({ page }) => {
	const title = `Recovery e2e ${Date.now()}`;
	await createGreekPassage(page, title);
	await startManualSession(page);
	await expect(page).toHaveURL(/\/practice\/[\w-]+/);
	const sessionUrl = page.url();

	await expect(page.getByText('Recite this line to the end.')).toBeVisible();
	await page.keyboard.press(' '); // check first — grading unlocks after the reveal
	await page.keyboard.press('3'); // "Good" → hesitant on item 1
	await expect(page.getByText(/Good · mastery/)).toBeVisible();

	// Simulate a crash: hard reload, then verify the same item cursor.
	await page.reload();
	await expect(page.getByText('1/2 items')).toBeVisible();
	await expect(page.getByRole('button', { name: /Show answer/ })).toBeVisible();

	// The practice list also offers recovery from the localStorage pointer.
	await page.goto('/practice');
	const resumeBanner = page.getByRole('link', { name: /where you left off/ });
	await expect(resumeBanner).toBeVisible();
	await resumeBanner.click();
	await expect(page).toHaveURL(sessionUrl);
	await expect(page.getByText('1/2 items')).toBeVisible();
});

test('Cmd+Z reopens the last graded card and rewinds the tally', async ({ page }) => {
	const title = `Undo e2e ${Date.now()}`;
	await createGreekPassage(page, title);
	await startManualSession(page);
	await expect(page).toHaveURL(/\/practice\/[\w-]+/);

	// Check, then grade item 1, advancing the cursor.
	await expect(page.getByText('Recite this line to the end.')).toBeVisible();
	await page.keyboard.press(' ');
	await page.keyboard.press('4');
	await expect(page.getByText('1/2 items')).toBeVisible();

	// Cmd/Ctrl+Z rolls the card back: the cursor returns and the first cue shows.
	await page.keyboard.press('ControlOrMeta+z');
	await expect(page.getByText('0/2 items')).toBeVisible();
	await expect(page.getByText('Recite this line to the end.')).toBeVisible();
	await expect(page.getByText('Undid the last card')).toBeVisible();

	// A second undo with nothing left is a no-op with a hint, not an error.
	await page.keyboard.press('ControlOrMeta+z');
	await expect(page.getByText('Nothing left to undo')).toBeVisible();
});

test('creating without generating segments still yields practiceable lines', async ({ page }) => {
	const title = `Autosegment e2e ${Date.now()}`;
	await page.goto('/passages/new');
	await page.getByLabel('Title').fill(title);
	await page.getByLabel('Language').selectOption({ label: 'Latin' });
	await page.getByLabel(/Source text/).fill('Arma virumque cano, Troiae qui primus ab oris');
	// Deliberately skip "Generate line segments".
	await page.getByRole('button', { name: 'Create passage' }).click();
	await expect(page).toHaveURL(/\/passages\/[\w-]+/);
	await startManualSession(page);
	await expect(page).toHaveURL(/\/practice\/[\w-]+/);
	await expect(page.getByText('0/1 items')).toBeVisible();
});

test('desktop two-column layout stacks on a phone viewport', async ({ page }) => {
	const title = `Responsive e2e ${Date.now()}`;
	await createGreekPassage(page, title);

	await page.setViewportSize({ width: 1280, height: 900 });
	const columns = page.locator('.columns');
	const desktopCols = await columns.evaluate(
		(element) => getComputedStyle(element).gridTemplateColumns.split(' ').length
	);
	expect(desktopCols).toBe(2);

	await page.setViewportSize({ width: 390, height: 800 });
	const phoneCols = await columns.evaluate(
		(element) => getComputedStyle(element).gridTemplateColumns.split(' ').length
	);
	expect(phoneCols).toBe(1);
});

test('smart session teaches fresh lines through acquisition while junctures keep fading', async ({ page }) => {
	const title = `Smart e2e ${Date.now()}`;
	await createGreekPassage(page, title);

	await page.getByRole('button', { name: '✦ Smart session' }).first().click();
	await expect(page).toHaveURL(/\/practice\/[\w-]+/);

	// A fresh passage deals ONLY its lines: the juncture between two not-yet-
	// started lines is gated until both flanks are known.
	await expect(page.getByText('0/2 items')).toBeVisible();

	// A fresh line gets encounter → supported reconstruction; the visible
	// check unlocks grading, and bare-cue production waits for a later visit.
	await expect(page.getByText('acquisition', { exact: true })).toBeVisible();
	await completeAcquisition(page);
	await page.keyboard.press('4');
	await expect(page.getByText('1/2 items')).toBeVisible();

	await expect(page.getByText('acquisition', { exact: true })).toBeVisible();
	await completeAcquisition(page);
	await page.keyboard.press('4');
	await expect(page.getByText('Session complete')).toBeVisible();

	// With both flanking lines started, the next session admits the juncture
	// on its established progressive-fading lesson.
	await page.goto('/');
	await page.getByRole('link', { name: title }).click();
	await page.getByRole('button', { name: '✦ Smart session' }).first().click();
	await expect(page).toHaveURL(/\/practice\/[\w-]+/);
	await expect(page.getByText('0/3 items')).toBeVisible();
});

test('smart sessions rotate a learning line through distinct exercises', async ({ page }) => {
	const title = `Smart rotation e2e ${Date.now()}`;
	await createSingleLinePassage(page, title);
	const passageUrl = page.url();

	for (const expectedMode of [
		'acquisition',
		'cue recall',
		'word bank',
		'forward chaining'
	]) {
		await page.getByRole('button', { name: '✦ Smart session' }).first().click();
		await expect(page).toHaveURL(/\/practice\/[\w-]+/);
		await expect(page.getByText(expectedMode, { exact: true })).toBeVisible();
		if (expectedMode === 'acquisition') {
			await completeAcquisition(page);
		} else {
			const reveal = page.getByRole('button', { name: /Show answer/ });
			if (await reveal.isVisible()) await reveal.click();
		}
		await page.keyboard.press('3'); // Good keeps the line in learning.
		await expect(page.getByText('Session complete')).toBeVisible();
		await page.goto(passageUrl);
	}
});

test('recordings stay browser-local until explicitly saved as best', async ({ page }) => {
	const title = `Recording e2e ${Date.now()}`;
	await createGreekPassage(page, title);
	await startManualSession(page);

	const uploads: string[] = [];
	page.on('request', (request) => {
		if (request.url().includes('/api/v1/media') && request.method() === 'POST') {
			uploads.push(request.url());
		}
	});

	// The recorder is opt-in: speaking aloud is the act, the mic is optional.
	await expect(page.getByRole('button', { name: '● Record' })).not.toBeVisible();
	await page.getByRole('button', { name: /enable recording/ }).click();

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

test('deleting a passage takes a two-step confirm and clears the library', async ({ page }) => {
	const title = `Delete e2e ${Date.now()}`;
	await createGreekPassage(page, title);

	// Step one only opens the confirm — nothing is deleted yet.
	await page.getByRole('button', { name: 'Delete this passage…' }).click();
	await expect(page.getByText(/cannot be undone/)).toBeVisible();

	await page.getByRole('button', { name: 'Yes, delete it all' }).click();
	await expect(page.getByRole('heading', { name: 'Your repertoire' })).toBeVisible();
	await expect(page.getByText(title)).not.toBeVisible();
});

test('adding lines to a practiced passage keeps it in place, no fork', async ({ page }) => {
	const title = `Append e2e ${Date.now()}`;
	await createGreekPassage(page, title);

	// Practice once so the revision becomes immutable to edits.
	await startManualSession(page);
	await expect(page.getByText('Recite this line to the end.')).toBeVisible();
	await page.keyboard.press(' ');
	await page.keyboard.press('3');
	await page.goto('/');
	await page.getByRole('link', { name: title }).click();

	// Append two lines — no revision fork, no lost progress.
	await page.getByRole('button', { name: '+ Add lines' }).click();
	await page.getByLabel(/Paste new lines/).fill('τρίτος στίχος\nτέταρτος στίχος');
	await page.getByRole('button', { name: '+ Append lines' }).click();

	await expect(page.getByText('τρίτος στίχος').first()).toBeVisible();
	await expect(page.getByText('τέταρτος στίχος').first()).toBeVisible();
	// Still revision 1 — appending did not fork.
	await expect(page.getByText(/revision 1/)).toBeVisible();
});
