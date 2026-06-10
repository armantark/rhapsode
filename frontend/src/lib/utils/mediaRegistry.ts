/**
 * The contract has no media listing endpoint (only POST /media, DELETE, and
 * GET /media/{id}/content), so uploads are remembered client-side. A
 * GET /api/v1/media?revision_id=… listing is requested in
 * memory-bank/handoffs/frontend-to-backend.md; once it lands this registry
 * can be deleted.
 */
const REGISTRY_KEY = 'rhapsode.media.v1';

export interface MediaRecord {
	id: string;
	category: 'reference' | 'saved_best';
	revisionId: string | null;
	segmentId: string | null;
	name: string;
	mimeType: string;
	createdAt: string;
}

function load(): MediaRecord[] {
	try {
		return JSON.parse(globalThis.localStorage?.getItem(REGISTRY_KEY) ?? '[]') as MediaRecord[];
	} catch {
		return [];
	}
}

function save(records: MediaRecord[]): void {
	globalThis.localStorage?.setItem(REGISTRY_KEY, JSON.stringify(records));
}

export function registerMedia(record: MediaRecord): void {
	save([...load().filter((existing) => existing.id !== record.id), record]);
}

export function forgetMedia(mediaId: string): void {
	save(load().filter((record) => record.id !== mediaId));
}

export function mediaForRevision(revisionId: string, category?: MediaRecord['category']): MediaRecord[] {
	return load().filter(
		(record) => record.revisionId === revisionId && (!category || record.category === category)
	);
}

export function savedBestMedia(): MediaRecord[] {
	return load().filter((record) => record.category === 'saved_best');
}
