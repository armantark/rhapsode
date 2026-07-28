import { expect, test, type APIRequestContext } from '@playwright/test';

const BACKEND = 'http://127.0.0.1:8643';

// Five lines is the smallest passage that keeps material outside the widest
// window (3), so "locked" is observable without depending on the setting.
const LINES = [
	'μῆνιν ἄειδε θεὰ Πηληϊάδεω Ἀχιλῆος',
	'οὐλομένην, ἣ μυρί᾽ Ἀχαιοῖς ἄλγε᾽ ἔθηκε',
	'πολλὰς δ᾽ ἰφθίμους ψυχὰς Ἄϊδι προΐαψεν',
	'ἡρώων, αὐτοὺς δὲ ἑλώρια τεῦχε κύνεσσιν',
	'οἰωνοῖσί τε πᾶσι, Διὸς δ᾽ ἐτελείετο βουλή'
];

/** The guided ladder's modes. A line stops producing these once mastered, so
 * their absence is the observable end of acquisition. Chain and full-passage
 * items also carry a mastered-prefix line's segment id (they are finishers
 * anchored on the prefix), which is why they must not count as ladder work. */
const LADDER_MODES = new Set([
	'acquisition',
	'guided_recall',
	'progressive_fading',
	'word_bank',
	'cue_recall',
	'typed_recall',
	'meaning_recall'
]);

interface Segment {
	id: string;
	kind: string;
	ordinal: number;
	text: string;
}

interface PracticeItem {
	id: string;
	segment_id: string | null;
	position: number;
	mode: string;
}

interface Session {
	id: string;
	items: PracticeItem[];
}

interface Passage {
	id: string;
	active_revision: { id: string; segments: Segment[] } | null;
}

let idempotencyCounter = 0;

function mutationHeaders(): Record<string, string> {
	idempotencyCounter += 1;
	return { 'Idempotency-Key': `e2e-runway-${Date.now()}-${idempotencyCounter}` };
}

async function setLinearWindow(request: APIRequestContext, value: number): Promise<void> {
	const response = await request.put(`${BACKEND}/api/v1/settings/linear_window`, {
		data: { value },
		headers: mutationHeaders()
	});
	expect(response.ok()).toBe(true);
}

async function createPassage(request: APIRequestContext, title: string): Promise<Passage> {
	const languagesResponse = await request.get(`${BACKEND}/api/v1/languages`);
	expect(languagesResponse.ok()).toBe(true);
	const languages = (await languagesResponse.json()) as Array<{ id: string; slug: string }>;
	const language = languages.find((item) => item.slug === 'ancient-greek') ?? languages[0];
	expect(language).toBeTruthy();

	// Segmentation is client-side (the creation form's "Generate line
	// segments" button), so the fixture supplies explicit line segments the
	// same way the form does; the server derives junctures from them.
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

function linesOf(passage: Passage): Segment[] {
	const segments = passage.active_revision?.segments ?? [];
	return segments
		.filter((segment) => segment.kind === 'line')
		.sort((first, second) => first.ordinal - second.ordinal);
}

async function startSmartSession(
	request: APIRequestContext,
	revisionId: string
): Promise<Session> {
	const response = await request.post(`${BACKEND}/api/v1/sessions`, {
		data: { revision_id: revisionId },
		headers: mutationHeaders()
	});
	expect(response.ok()).toBe(true);
	return (await response.json()) as Session;
}

async function gradeClean(
	request: APIRequestContext,
	sessionId: string,
	itemId: string
): Promise<void> {
	const response = await request.post(`${BACKEND}/api/v1/sessions/${sessionId}/attempts`, {
		data: { item_id: itemId, rating: 'clean', revealed: false },
		headers: mutationHeaders()
	});
	expect(response.ok()).toBe(true);
}

async function completeSession(request: APIRequestContext, sessionId: string): Promise<void> {
	const response = await request.post(`${BACKEND}/api/v1/sessions/${sessionId}/complete`, {
		data: {},
		headers: mutationHeaders()
	});
	expect(response.ok()).toBe(true);
}

/**
 * Drive one line's guided ladder to completion through the API, the way the
 * existing specs seed state. Each round starts a smart session, grades only the
 * target line's ladder items clean, and abandons the rest, so neighbouring
 * lines stay unmastered and the window boundary remains observable. Mastery is
 * read from the review state's own gate — a mastered line keeps appearing in
 * sessions (warmup, reviews), so "no more ladder cards" is not a signal.
 */
async function masterLine(
	request: APIRequestContext,
	revisionId: string,
	segmentId: string
): Promise<void> {
	for (let round = 0; round < 40; round += 1) {
		const session = await startSmartSession(request, revisionId);
		const ladderItems = session.items.filter(
			(item) => item.segment_id === segmentId && LADDER_MODES.has(item.mode)
		);
		for (const item of ladderItems) {
			await gradeClean(request, session.id, item.id);
		}
		await completeSession(request, session.id);
		const statesResponse = await request.get(
			`${BACKEND}/api/v1/analytics/due?before=2999-01-01T00:00:00Z`
		);
		expect(statesResponse.ok()).toBe(true);
		const states = (await statesResponse.json()) as Array<{
			segment_id: string;
			acquisition_succeeded: boolean;
			learning_step: number | null;
		}>;
		const state = states.find((candidate) => candidate.segment_id === segmentId);
		if (state && state.acquisition_succeeded && state.learning_step === null) {
			return;
		}
	}
	throw new Error(`Line ${segmentId} did not finish its ladder within 40 sessions.`);
}

test.beforeEach(async ({ request }) => {
	// The suite shares one backend database, so the window is pinned rather
	// than assumed to still hold its default.
	await setLinearWindow(request, 3);
});

test('a fresh passage deals its window in passage order and locks the rest', async ({
	request
}) => {
	const passage = await createPassage(request, `Runway order e2e ${Date.now()}`);
	const revisionId = passage.active_revision?.id;
	expect(revisionId).toBeTruthy();
	const lines = linesOf(passage);
	expect(lines).toHaveLength(LINES.length);

	const session = await startSmartSession(request, revisionId as string);
	expect(session.items.length).toBeGreaterThan(0);

	const ordinalById = new Map(lines.map((line) => [line.id, line.ordinal]));
	const dealtOrdinals = session.items
		.map((item) => (item.segment_id === null ? undefined : ordinalById.get(item.segment_id)))
		.filter((ordinal): ordinal is number => ordinal !== undefined);

	// Recitation is sequential, so the plan may never jump backwards.
	const sorted = [...dealtOrdinals].sort((first, second) => first - second);
	expect(dealtOrdinals).toEqual(sorted);

	// Nothing past the window: lines 4 and 5 are locked on a fresh passage.
	const lockedIds = new Set(lines.slice(3).map((line) => line.id));
	const lockedItems = session.items.filter(
		(item) => item.segment_id !== null && lockedIds.has(item.segment_id)
	);
	expect(lockedItems).toEqual([]);
});

test('a mastered first line reads mastered on the runway and advances the window', async ({
	page,
	request
}) => {
	const passage = await createPassage(request, `Runway advance e2e ${Date.now()}`);
	const revisionId = passage.active_revision?.id as string;
	const lines = linesOf(passage);
	await masterLine(request, revisionId, lines[0].id);

	await page.goto(`/passages/${passage.id}`);
	const cells = page.locator('[data-testid="runway-cell"]');
	await expect(cells).toHaveCount(LINES.length);

	// Line 1 is done, so the window slides to lines 2–4 and only line 5 stays
	// locked — the whole point of the runway being linear.
	await expect(cells.nth(0)).toHaveAttribute('data-state', 'mastered');
	await expect(cells.nth(1)).toHaveAttribute('data-state', 'active');
	await expect(cells.nth(2)).toHaveAttribute('data-state', 'active');
	await expect(cells.nth(3)).toHaveAttribute('data-state', 'active');
	await expect(cells.nth(4)).toHaveAttribute('data-state', 'locked');
});

test('two mastered lines earn a forward-chain finisher at the end of the session', async ({
	request
}) => {
	const passage = await createPassage(request, `Runway finisher e2e ${Date.now()}`);
	const revisionId = passage.active_revision?.id as string;
	const lines = linesOf(passage);
	await masterLine(request, revisionId, lines[0].id);
	await masterLine(request, revisionId, lines[1].id);

	const session = await startSmartSession(request, revisionId);
	const last = session.items[session.items.length - 1];
	expect(last.mode).toBe('forward_chaining');
	// The finisher chains the mastered prefix and is credited to its NEWEST
	// line, so line 1's own mode rotation is not skewed by every session.
	expect(last.segment_id).toBe(lines[1].id);
});

test('random start never appears in a smart plan', async ({ request }) => {
	const passage = await createPassage(request, `Runway no-random e2e ${Date.now()}`);
	const revisionId = passage.active_revision?.id as string;
	const lines = linesOf(passage);

	const fresh = await startSmartSession(request, revisionId);
	expect(fresh.items.map((item) => item.mode)).not.toContain('random_start');

	// Also once a prefix exists: random_start is manual-only at every stage,
	// not merely absent while the passage is new.
	await masterLine(request, revisionId, lines[0].id);
	const later = await startSmartSession(request, revisionId);
	expect(later.items.map((item) => item.mode)).not.toContain('random_start');
});
