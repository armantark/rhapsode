import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type {
	AttemptResult,
	LanguageProfile,
	Passage,
	PracticeItem,
	PracticeSession,
	Revision,
	Today
} from '$lib/api/types';

// The practice page is the latency-critical screen: a grade tap must paint the
// next card from state already in memory while the attempt posts in the
// background. These tests hold the POST open on purpose, so what they assert is
// exactly what the learner sees during the round trip.
const { api } = vi.hoisted(() => ({
	api: {
		getSession: vi.fn(),
		listLanguages: vi.fn(),
		getRevision: vi.fn(),
		getPassage: vi.fn(),
		listMedia: vi.fn(),
		getCollection: vi.fn(),
		getNote: vi.fn(),
		putNote: vi.fn(),
		submitAttempt: vi.fn(),
		undoAttempt: vi.fn(),
		completeSession: vi.fn(),
		createSession: vi.fn(),
		uploadMedia: vi.fn(),
		today: vi.fn(),
		mediaUrl: vi.fn(() => '')
	}
}));

vi.mock('$lib/api/client', () => ({ api, isConflict: () => false }));
vi.mock('$app/state', () => ({ page: { params: { id: 'session-1' } } }));

import PracticePage from './+page.svelte';

const PROFILE: LanguageProfile = {
	id: 'lp-1',
	slug: 'greek',
	name: 'Ancient Greek',
	direction: 'ltr',
	fonts: [],
	annotation_schemas: [],
	segmentation_defaults: {},
	display_options: {}
};

const PASSAGE: Passage = {
	id: 'pas-1',
	title: 'Iliad',
	description: null,
	language_profile_id: 'lp-1',
	active_revision_id: 'rev-1'
};

function segment(id: string, ordinal: number, text: string) {
	return {
		id,
		revision_id: 'rev-1',
		kind: 'line',
		text,
		ordinal,
		parent_id: null,
		reference_label: null,
		cue: null,
		annotations: [],
		metadata_json: {}
	};
}

const REVISION: Revision = {
	id: 'rev-1',
	passage_id: 'pas-1',
	revision_number: 1,
	source_text: 'line one\nline two',
	reference_label: null,
	practiced: true,
	hierarchy: {},
	segments: [segment('seg-1', 0, 'line one'), segment('seg-2', 1, 'line two')]
};

function item(id: string, position: number, instruction: string, completed = false): PracticeItem {
	return {
		id,
		session_id: 'session-1',
		revision_id: 'rev-1',
		segment_id: position === 0 ? 'seg-1' : 'seg-2',
		position,
		mode: 'cue_recall',
		prompt: { instruction },
		completed
	};
}

function session(items: PracticeItem[], overrides: Partial<PracticeSession> = {}): PracticeSession {
	return {
		id: 'session-1',
		revision_id: 'rev-1',
		collection_id: null,
		status: 'active',
		current_index: 0,
		completed_at: null,
		plan: {},
		items,
		...overrides
	};
}

function attemptResult(next: PracticeSession, rating = 'clean'): AttemptResult {
	return {
		attempt: {
			id: `att-${rating}`,
			session_id: 'session-1',
			item_id: 'item-1',
			segment_id: 'seg-1',
			media_asset_id: null,
			mode: 'cue_recall',
			rating,
			revealed: true,
			latency_ms: 1,
			created_at: new Date().toISOString()
		},
		session: next,
		due_at: null,
		mastery_stage: 'learning'
	};
}

const TODAY: Today = {
	due_count: 0,
	estimated_minutes: 0,
	desired_retention: 0.9,
	measured_retention: null,
	retention_sample: 0,
	streak_days: 1,
	forecast: []
};

function deferred<T>() {
	let resolve!: (value: T) => void;
	let reject!: (reason?: unknown) => void;
	const promise = new Promise<T>((settle, fail) => {
		resolve = settle;
		reject = fail;
	});
	return { promise, resolve, reject };
}

/** Let queued microtasks (and the promise chain the grade queue runs on) drain
 *  so "nothing happened yet" assertions are about behaviour, not timing luck. */
const settle = () => new Promise((done) => setTimeout(done, 0));

async function renderPractice() {
	render(PracticePage);
	await screen.findByText('Recite line one.');
}

async function revealAndGrade(label: string) {
	await fireEvent.click(await screen.findByRole('button', { name: 'Show answer to check' }));
	await fireEvent.click(await screen.findByRole('button', { name: label }));
}

beforeEach(() => {
	vi.clearAllMocks();
	localStorage.clear();
	Object.defineProperty(window, 'matchMedia', {
		writable: true,
		configurable: true,
		value: () => ({ matches: true, addEventListener() {}, removeEventListener() {} })
	});
	api.getSession.mockResolvedValue(
		session([item('item-1', 0, 'Recite line one.'), item('item-2', 1, 'Recite line two.')])
	);
	api.listLanguages.mockResolvedValue([PROFILE]);
	api.getRevision.mockResolvedValue(REVISION);
	api.getPassage.mockResolvedValue(PASSAGE);
	api.listMedia.mockResolvedValue([]);
	api.getNote.mockResolvedValue(null);
	api.today.mockResolvedValue(TODAY);
});

describe('practice grading', () => {
	it('shows the next card before the attempt post resolves', async () => {
		const post = deferred<AttemptResult>();
		api.submitAttempt.mockReturnValue(post.promise);

		await renderPractice();
		await revealAndGrade('4 Easy');

		// The whole point: the next card and the progress counter are already on
		// screen while the request is still open.
		expect(api.submitAttempt).toHaveBeenCalledTimes(1);
		expect(screen.getByText('Recite line two.')).toBeInTheDocument();
		expect(screen.getByText('1/2 items')).toBeInTheDocument();

		post.resolve(
			attemptResult(
				session(
					[
						item('item-1', 0, 'Recite line one.', true),
						item('item-2', 1, 'Recite line two, with support.')
					],
					{ current_index: 1 }
				)
			)
		);
		// The dealt card's support is materialized server-side, so the response
		// upgrades the prompt of the card the learner is already looking at.
		expect(await screen.findByText('Recite line two, with support.')).toBeInTheDocument();
	});

	it('keeps a revealed card intact when a response upgrades its prompt', async () => {
		const post = deferred<AttemptResult>();
		api.submitAttempt.mockReturnValue(post.promise);

		await renderPractice();
		await revealAndGrade('4 Easy');
		await fireEvent.click(await screen.findByRole('button', { name: 'Show answer to check' }));
		expect(screen.getByText('line two', { selector: '.revealed-text' })).toBeInTheDocument();

		post.resolve(
			attemptResult(
				session([
					item('item-1', 0, 'Recite line one.', true),
					item('item-2', 1, 'Recite line two, with support.')
				])
			)
		);
		await settle();

		// Swapping the prompt under a checked card would move the answer mid-read.
		expect(screen.getByText('Recite line two.')).toBeInTheDocument();
		expect(screen.getByText('line two', { selector: '.revealed-text' })).toBeInTheDocument();
	});

	it('serializes queued grades and only celebrates once the last one lands', async () => {
		const first = deferred<AttemptResult>();
		const second = deferred<AttemptResult>();
		api.submitAttempt.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

		await renderPractice();
		await revealAndGrade('4 Easy');
		await revealAndGrade('3 Good');

		// Two grades pressed, one request in flight: the backend advances the
		// cursor per attempt, so they must not overlap.
		await settle();
		expect(api.submitAttempt).toHaveBeenCalledTimes(1);
		expect(screen.getByText('2/2 items')).toBeInTheDocument();
		expect(screen.queryByText('Session complete')).not.toBeInTheDocument();
		expect(screen.getByText('Filing your last card…')).toBeInTheDocument();

		first.resolve(
			attemptResult(
				session([
					item('item-1', 0, 'Recite line one.', true),
					item('item-2', 1, 'Recite line two.')
				])
			)
		);
		await waitFor(() => expect(api.submitAttempt).toHaveBeenCalledTimes(2));
		expect(api.submitAttempt.mock.calls[0][1].item_id).toBe('item-1');
		expect(api.submitAttempt.mock.calls[1][1].item_id).toBe('item-2');
		expect(screen.queryByText('Session complete')).not.toBeInTheDocument();

		second.resolve(
			attemptResult(
				session(
					[
						item('item-1', 0, 'Recite line one.', true),
						item('item-2', 1, 'Recite line two.', true)
					],
					{ status: 'completed' }
				),
				'hesitant'
			)
		);
		expect(await screen.findByText('Session complete')).toBeInTheDocument();
		const tally = [...document.querySelectorAll('.summary li')].map((entry) => entry.textContent);
		expect(tally).toEqual(['Easy × 1', 'Good × 1', 'Hard × 0', 'Again × 0']);
		// The server completed the session with the final attempt; the page must
		// not post a redundant completion on top of it.
		expect(api.completeSession).not.toHaveBeenCalled();
	});

	it('returns the learner to the card whose grade failed', async () => {
		api.submitAttempt.mockRejectedValue(new Error('offline'));

		await renderPractice();
		await revealAndGrade('4 Easy');

		expect(await screen.findByText(/Could not submit the attempt/)).toBeInTheDocument();
		// No grade may be lost silently: the failed card comes back, uncounted.
		expect(screen.getByText('Recite line one.')).toBeInTheDocument();
		expect(screen.getByText('0/2 items')).toBeInTheDocument();
	});

	it('drops the queue behind a failed grade instead of desyncing the tally', async () => {
		const first = deferred<AttemptResult>();
		api.submitAttempt.mockReturnValueOnce(first.promise).mockRejectedValue(new Error('offline'));

		await renderPractice();
		await revealAndGrade('4 Easy');
		await revealAndGrade('3 Good');

		first.resolve(
			attemptResult(
				session([
					item('item-1', 0, 'Recite line one.', true),
					item('item-2', 1, 'Recite line two.')
				])
			)
		);

		expect(await screen.findByText(/Could not submit the attempt/)).toBeInTheDocument();
		expect(screen.getByText('Recite line two.')).toBeInTheDocument();
		expect(screen.getByText('1/2 items')).toBeInTheDocument();
	});

	it('holds undo until the in-flight grade has landed', async () => {
		const post = deferred<AttemptResult>();
		api.submitAttempt.mockReturnValue(post.promise);
		const undone = session([
			item('item-1', 0, 'Recite line one.'),
			item('item-2', 1, 'Recite line two.')
		]);
		api.undoAttempt.mockResolvedValue(undone);

		await renderPractice();
		await revealAndGrade('4 Easy');
		await fireEvent.keyDown(window, { key: 'z', metaKey: true });

		// Undoing before the grade exists server-side would pop the wrong attempt.
		await settle();
		expect(api.undoAttempt).not.toHaveBeenCalled();

		post.resolve(
			attemptResult(
				session([
					item('item-1', 0, 'Recite line one.', true),
					item('item-2', 1, 'Recite line two.')
				])
			)
		);
		await waitFor(() => expect(api.undoAttempt).toHaveBeenCalledTimes(1));
		expect(await screen.findByText('Undid the last card')).toBeInTheDocument();
		expect(screen.getByText('0/2 items')).toBeInTheDocument();
	});
});
