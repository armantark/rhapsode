import type {
	Annotation,
	AnnotationCreate,
	AttemptCreate,
	AttemptResult,
	Collection,
	CollectionCreate,
	CuePoint,
	Health,
	LanguageProfile,
	LibraryPassageStats,
	Media,
	MediaCategory,
	Passage,
	PassageDetail,
	PassageInput,
	PersonalNote,
	PracticeSession,
	PrepSuggestResult,
	Today,
	Revision,
	RevisionInput,
	ReviewState,
	SegmentInput,
	SessionCreate,
	Setting,
	SystemStatus,
	WeakLink
} from './types';
import { getApiBase } from './platform';

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
	const base = getApiBase();
	const origin = base.startsWith('http') ? undefined : (globalThis.location?.origin ?? 'http://localhost');
	const url = new URL(base + path, origin);
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
	systemStatus: () => send<SystemStatus>('GET', '/system/status'),

	listLanguages: () => send<LanguageProfile[]>('GET', '/languages'),

	listPassages: () => send<Passage[]>('GET', '/passages'),
	getPassage: (passageId: string) => send<PassageDetail>('GET', `/passages/${passageId}`),
	createPassage: (input: PassageInput, key?: string) =>
		send<PassageDetail>('POST', '/passages', { body: input, key }),
	deletePassage: (passageId: string, key?: string) =>
		send<Record<string, boolean>>('DELETE', `/passages/${passageId}`, { key }),

	getRevision: (revisionId: string) => send<Revision>('GET', `/revisions/${revisionId}`),
	createRevision: (passageId: string, input: RevisionInput, key?: string) =>
		send<Revision>('POST', `/passages/${passageId}/revisions`, { body: input, key }),
	replaceSegments: (revisionId: string, segments: SegmentInput[], key?: string) =>
		send<Revision>('PUT', `/revisions/${revisionId}/segments`, { body: { segments }, key }),

	// A 404 means the segment simply has no personal note yet — a normal state,
	// not an error, so callers get null instead of a thrown ApiError.
	getNote: async (segmentId: string): Promise<PersonalNote | null> => {
		try {
			return await send<PersonalNote>('GET', `/segments/${segmentId}/note`);
		} catch (error) {
			if (error instanceof ApiError && error.status === 404) return null;
			throw error;
		}
	},
	putNote: (segmentId: string, text: string, key?: string) =>
		send<PersonalNote>('PUT', `/segments/${segmentId}/note`, { body: { text }, key }),

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
	setMediaCues: (mediaId: string, cuePoints: CuePoint[], key?: string) =>
		send<Media>('PUT', `/media/${mediaId}/cues`, { body: { cue_points: cuePoints }, key }),
	listMedia: (revisionId?: string, category?: MediaCategory) =>
		send<Media[]>('GET', '/media', { query: { revision_id: revisionId, category } }),
	mediaUrl: (mediaId: string) => `${getApiBase()}/media/${mediaId}/content`,

	listCollections: () => send<Collection[]>('GET', '/collections'),
	getCollection: (collectionId: string) =>
		send<Collection>('GET', `/collections/${collectionId}`),
	createCollection: (input: CollectionCreate, key?: string) =>
		send<Collection>('POST', '/collections', { body: input, key }),
	updateCollection: (collectionId: string, input: CollectionCreate, key?: string) =>
		send<Collection>('PUT', `/collections/${collectionId}`, { body: input, key }),
	deleteCollection: (collectionId: string, key?: string) =>
		send<Record<string, boolean>>('DELETE', `/collections/${collectionId}`, { key }),
	addCollectionMember: (collectionId: string, passageId: string, key?: string) =>
		send<Collection>('POST', `/collections/${collectionId}/members`, {
			body: { passage_id: passageId },
			key
		}),
	removeCollectionMember: (collectionId: string, passageId: string, key?: string) =>
		send<Collection>('DELETE', `/collections/${collectionId}/members/${passageId}`, { key }),
	reorderCollectionMembers: (collectionId: string, passageIds: string[], key?: string) =>
		send<Collection>('PUT', `/collections/${collectionId}/members`, {
			body: { passage_ids: passageIds },
			key
		}),

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

	today: () => send<Today>('GET', '/analytics/today'),
	libraryStats: () => send<LibraryPassageStats[]>('GET', '/analytics/library'),
	dueReviews: (before?: string) => send<ReviewState[]>('GET', '/analytics/due', { query: { before } }),
	weakLinks: (revisionId?: string) =>
		send<WeakLink[]>('GET', '/analytics/weak-links', { query: { revision_id: revisionId } }),

	listSettings: () => send<Setting[]>('GET', '/settings'),
	putSetting: (settingKey: string, value: unknown, key?: string) =>
		send<Setting>('PUT', `/settings/${settingKey}`, { body: { value }, key })
};
