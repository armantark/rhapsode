import type {
	Annotation,
	AnnotationCreate,
	AttemptCreate,
	AttemptResult,
	Health,
	LanguageProfile,
	Media,
	MediaCategory,
	Passage,
	PassageDetail,
	PassageInput,
	PracticeSession,
	PrepSuggestResult,
	Revision,
	RevisionInput,
	ReviewState,
	SegmentInput,
	SessionCreate,
	Setting,
	WeakLink
} from './types';

const BASE = '/api/v1';

export class ApiError extends Error {
	readonly status: number;
	readonly detail: unknown;

	constructor(status: number, detail: unknown) {
		super(typeof detail === 'string' ? detail : `Request failed (${status})`);
		this.status = status;
		this.detail = detail;
	}
}

/** Practiced revisions are immutable; 409 means "fork a new revision". */
export function isConflict(error: unknown): error is ApiError {
	return error instanceof ApiError && error.status === 409;
}

export function newIdempotencyKey(): string {
	return globalThis.crypto?.randomUUID?.() ?? `ik-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

interface SendOptions {
	body?: unknown;
	form?: FormData;
	query?: Record<string, string | undefined>;
	key?: string;
}

async function send<T>(method: string, path: string, options: SendOptions = {}): Promise<T> {
	const url = new URL(BASE + path, globalThis.location?.origin ?? 'http://localhost');
	for (const [name, value] of Object.entries(options.query ?? {})) {
		if (value !== undefined) url.searchParams.set(name, value);
	}
	const headers: Record<string, string> = {};
	const mutating = method !== 'GET';
	// One key per logical mutation: a retry with the same key makes the
	// backend replay the stored response instead of re-applying the change.
	const key = options.key ?? newIdempotencyKey();
	if (mutating) headers['Idempotency-Key'] = key;
	const init: RequestInit = { method, headers };
	if (options.form) {
		init.body = options.form;
	} else if (options.body !== undefined) {
		headers['Content-Type'] = 'application/json';
		init.body = JSON.stringify(options.body);
	}

	let response: Response;
	try {
		response = await fetch(url, init);
	} catch (networkError) {
		if (!mutating) throw networkError;
		response = await fetch(url, init);
	}
	if (!response.ok) {
		let detail: unknown = null;
		try {
			detail = ((await response.json()) as { detail?: unknown }).detail;
		} catch {
			// non-JSON error body; status alone is enough
		}
		throw new ApiError(response.status, detail);
	}
	return (await response.json()) as T;
}

export const api = {
	health: () => send<Health>('GET', '/health'),

	listLanguages: () => send<LanguageProfile[]>('GET', '/languages'),

	listPassages: () => send<Passage[]>('GET', '/passages'),
	getPassage: (passageId: string) => send<PassageDetail>('GET', `/passages/${passageId}`),
	createPassage: (input: PassageInput, key?: string) =>
		send<PassageDetail>('POST', '/passages', { body: input, key }),

	getRevision: (revisionId: string) => send<Revision>('GET', `/revisions/${revisionId}`),
	createRevision: (passageId: string, input: RevisionInput, key?: string) =>
		send<Revision>('POST', `/passages/${passageId}/revisions`, { body: input, key }),
	replaceSegments: (revisionId: string, segments: SegmentInput[], key?: string) =>
		send<Revision>('PUT', `/revisions/${revisionId}/segments`, { body: { segments }, key }),

	createAnnotation: (input: AnnotationCreate, key?: string) =>
		send<Annotation>('POST', '/annotations', { body: input, key }),
	suggestPrep: (revisionId: string, layers?: string[], key?: string) =>
		send<PrepSuggestResult>('POST', `/revisions/${revisionId}/prep-suggestions`, {
			body: layers ? { layers } : {},
			key
		}),
	deleteAnnotation: (annotationId: string, key?: string) =>
		send<Record<string, boolean>>('DELETE', `/annotations/${annotationId}`, { key }),

	uploadMedia: (
		file: Blob,
		category: MediaCategory,
		refs: { revisionId?: string; segmentId?: string; filename?: string } = {},
		key?: string
	) => {
		const form = new FormData();
		form.set('category', category);
		if (refs.revisionId) form.set('revision_id', refs.revisionId);
		if (refs.segmentId) form.set('segment_id', refs.segmentId);
		form.set('upload', file, refs.filename ?? 'recording.webm');
		return send<Media>('POST', '/media', { form, key });
	},
	deleteMedia: (mediaId: string, key?: string) =>
		send<Record<string, boolean>>('DELETE', `/media/${mediaId}`, { key }),
	listMedia: (revisionId?: string, category?: MediaCategory) =>
		send<Media[]>('GET', '/media', { query: { revision_id: revisionId, category } }),
	mediaUrl: (mediaId: string) => `${BASE}/media/${mediaId}/content`,

	listSessions: (status?: string) =>
		send<PracticeSession[]>('GET', '/sessions', { query: { status } }),
	getSession: (sessionId: string) => send<PracticeSession>('GET', `/sessions/${sessionId}`),
	createSession: (input: SessionCreate, key?: string) =>
		send<PracticeSession>('POST', '/sessions', { body: input, key }),
	submitAttempt: (sessionId: string, attempt: AttemptCreate, key?: string) =>
		send<AttemptResult>('POST', `/sessions/${sessionId}/attempts`, { body: attempt, key }),
	undoAttempt: (sessionId: string, key?: string) =>
		send<PracticeSession>('POST', `/sessions/${sessionId}/undo`, { key }),
	completeSession: (sessionId: string, key?: string) =>
		send<PracticeSession>('POST', `/sessions/${sessionId}/complete`, { key }),

	dueReviews: (before?: string) => send<ReviewState[]>('GET', '/analytics/due', { query: { before } }),
	weakLinks: (revisionId?: string) =>
		send<WeakLink[]>('GET', '/analytics/weak-links', { query: { revision_id: revisionId } }),

	listSettings: () => send<Setting[]>('GET', '/settings'),
	putSetting: (settingKey: string, value: unknown, key?: string) =>
		send<Setting>('PUT', `/settings/${settingKey}`, { body: { value }, key })
};
