import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const BACKEND = 'http://127.0.0.1:8643';

// Six lines put the picked range (4–5) well past the widest runway window (3),
// so a scoped session is only explainable by the override, not by the lock.
const LINES = [
	'μῆνιν ἄειδε θεὰ Πηληϊάδεω Ἀχιλῆος',
	'οὐλομένην, ἣ μυρί᾽ Ἀχαιοῖς ἄλγε᾽ ἔθηκε',
	'πολλὰς δ᾽ ἰφθίμους ψυχὰς Ἄϊδι προΐαψεν',
	'ἡρώων, αὐτοὺς δὲ ἑλώρια τεῦχε κύνεσσιν',
	'οἰωνοῖσί τε πᾶσι, Διὸς δ᾽ ἐτελείετο βουλή',
	'ἐξ οὗ δὴ τὰ πρῶτα διαστήτην ἐρίσαντε'
];

interface Segment {
	id: string;
	kind: string;
	ordinal: number;
}

interface Passage {
	id: string;
	active_revision: { id: string; segments: Segment[] } | null;
}

let idempotencyCounter = 0;

function mutationHeaders(): Record<string, string> {
	idempotencyCounter += 1;
	return { 'Idempotency-Key': `e2e-range-${Date.now()}-${idempotencyCounter}` };
}

async function createPassage(request: APIRequestContext, title: string): Promise<Passage> {
	const languagesResponse = await request.get(`${BACKEND}/api/v1/languages`);
	expect(languagesResponse.ok()).toBe(true);
	const languages = (await languagesResponse.json()) as Array<{ id: string; slug: string }>;
	const language = languages.find((item) => item.slug === 'ancient-greek') ?? languages[0];

	const response = await request.post(`${BACKEND}/api/v1/passages`, {
		data: {
			title,
			language_profile_id: language.id,
			source_text: LINES.join('\n'),
			segments: LINES.map((text, index) => ({ kind: 'line', ordinal: index + 1, text }))
		},
		headers: mutationHeaders()
	});
	expect(response.ok()).toBe(true);
	return (await response.json()) as Passage;
}

async function pickRange(page: Page, start: number, end: number): Promise<void> {
	const cells = page.locator('[data-testid="runway-cell"]');
	await expect(cells).toHaveCount(LINES.length);
	await cells.nth(start - 1).click();
	await cells.nth(end - 1).click();
}

test.beforeEach(async ({ request }) => {
	// The suite shares one backend database, so the window is pinned rather
	// than assumed: "line 5 is locked" has to mean the same thing every run.
	const response = await request.put(`${BACKEND}/api/v1/settings/linear_window`, {
		data: { value: 3 },
		headers: mutationHeaders()
	});
	expect(response.ok()).toBe(true);
});

test('picking a range on the strip launches a session scoped to those lines', async ({
	page,
	request
}) => {
	const passage = await createPassage(request, `Range picker e2e ${Date.now()}`);
	await page.goto(`/passages/${passage.id}`);

	await pickRange(page, 4, 5);

	// Both endpoints and the span between them read as selected, and the
	// runway state underneath is preserved — selection is an overlay.
	const cells = page.locator('[data-testid="runway-cell"]');
	await expect(cells.nth(3)).toHaveAttribute('aria-pressed', 'true');
	await expect(cells.nth(4)).toHaveAttribute('aria-pressed', 'true');
	await expect(cells.nth(2)).toHaveAttribute('aria-pressed', 'false');
	await expect(cells.nth(4)).toHaveAttribute('data-state', 'locked');

	const [sessionResponse] = await Promise.all([
		page.waitForResponse(
			(response) =>
				response.url().includes('/api/v1/sessions') && response.request().method() === 'POST'
		),
		page.getByRole('button', { name: '✦ Practice lines 4–5' }).click()
	]);
	const session = (await sessionResponse.json()) as {
		id: string;
		plan: { line_start: number; line_end: number };
		items: Array<{ segment_id: string | null }>;
	};
	expect(session.plan.line_start).toBe(4);
	expect(session.plan.line_end).toBe(5);
	await expect(page).toHaveURL(new RegExp(`/practice/${session.id}$`));

	// Nothing outside the picked range is dealt, including the lines the
	// global runway would otherwise have opened on.
	const lines = (passage.active_revision?.segments ?? [])
		.filter((segment) => segment.kind === 'line')
		.sort((first, second) => first.ordinal - second.ordinal);
	const scoped = new Set([lines[3].id, lines[4].id]);
	const dealt = session.items
		.map((item) => item.segment_id)
		.filter((id): id is string => id !== null);
	expect(dealt.length).toBeGreaterThan(0);
	expect(dealt.every((id) => scoped.has(id))).toBe(true);
});

test('clearing the selection restores the plain runway caption', async ({ page, request }) => {
	const passage = await createPassage(request, `Range clear e2e ${Date.now()}`);
	await page.goto(`/passages/${passage.id}`);

	await pickRange(page, 2, 3);
	await expect(page.getByTestId('runway-range')).toBeVisible();

	await page.getByRole('button', { name: 'Clear' }).click();
	await expect(page.getByTestId('runway-range')).toHaveCount(0);
	await expect(page.getByText('Tap two lines to practice that range instead.')).toBeVisible();
});
