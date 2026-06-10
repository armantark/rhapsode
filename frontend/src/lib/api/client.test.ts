import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, isConflict, newIdempotencyKey } from './client';

function jsonResponse(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'Content-Type': 'application/json' }
	});
}

afterEach(() => {
	vi.restoreAllMocks();
});

describe('idempotency keys', () => {
	it('omits the header on reads', async () => {
		const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse([]));
		await api.listPassages();
		const headers = fetchMock.mock.calls[0][1]?.headers as Record<string, string>;
		expect(headers['Idempotency-Key']).toBeUndefined();
	});

	it('stamps every mutation with a key', async () => {
		const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({}, 201));
		await api.createSession({ revision_id: 'rev-1' });
		const headers = fetchMock.mock.calls[0][1]?.headers as Record<string, string>;
		expect(headers['Idempotency-Key']).toBeTruthy();
	});

	it('honors a caller-supplied key so retries replay the same mutation', async () => {
		const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({}, 201));
		await api.createSession({ revision_id: 'rev-1' }, 'fixed-key');
		const headers = fetchMock.mock.calls[0][1]?.headers as Record<string, string>;
		expect(headers['Idempotency-Key']).toBe('fixed-key');
	});

	it('retries a failed mutation once, reusing the identical key', async () => {
		const fetchMock = vi
			.spyOn(globalThis, 'fetch')
			.mockRejectedValueOnce(new TypeError('network down'))
			.mockResolvedValue(jsonResponse({}, 201));
		await api.completeSession('session-1');
		expect(fetchMock).toHaveBeenCalledTimes(2);
		const first = fetchMock.mock.calls[0][1]?.headers as Record<string, string>;
		const second = fetchMock.mock.calls[1][1]?.headers as Record<string, string>;
		expect(first['Idempotency-Key']).toBe(second['Idempotency-Key']);
	});

	it('does not retry reads', async () => {
		const fetchMock = vi
			.spyOn(globalThis, 'fetch')
			.mockRejectedValue(new TypeError('network down'));
		await expect(api.listPassages()).rejects.toThrow('network down');
		expect(fetchMock).toHaveBeenCalledTimes(1);
	});

	it('generates unique keys', () => {
		expect(newIdempotencyKey()).not.toBe(newIdempotencyKey());
	});
});

describe('error handling', () => {
	it('surfaces 409 as a conflict for the fork-revision flow', async () => {
		vi.spyOn(globalThis, 'fetch').mockResolvedValue(
			jsonResponse({ detail: 'Practiced revisions are immutable.' }, 409)
		);
		const failure = await api.replaceSegments('rev-1', []).catch((error: unknown) => error);
		expect(failure).toBeInstanceOf(ApiError);
		expect(isConflict(failure)).toBe(true);
		expect((failure as ApiError).message).toBe('Practiced revisions are immutable.');
	});

	it('keeps non-conflict statuses distinguishable', async () => {
		vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ detail: 'nope' }, 422));
		const failure = await api.createPassage({
			title: 't',
			language_profile_id: 'x',
			source_text: 's'
		}).catch((error: unknown) => error);
		expect(isConflict(failure)).toBe(false);
		expect((failure as ApiError).status).toBe(422);
	});
});

describe('smart sessions', () => {
	it('omits modes entirely so the backend planner stays in charge', async () => {
		const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({}, 201));
		await api.createSession({ revision_id: 'rev-1', due_only: true });
		const body = JSON.parse(fetchMock.mock.calls[0][1]?.body as string);
		expect('modes' in body).toBe(false);
		expect(body.due_only).toBe(true);
	});
});

describe('media upload', () => {
	it('sends multipart form fields the contract expects', async () => {
		const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({}, 201));
		const blob = new Blob(['audio'], { type: 'audio/webm' });
		await api.uploadMedia(blob, 'saved_best', {
			revisionId: 'rev-1',
			segmentId: 'seg-1',
			filename: 'best.webm'
		});
		const body = fetchMock.mock.calls[0][1]?.body as FormData;
		expect(body.get('category')).toBe('saved_best');
		expect(body.get('revision_id')).toBe('rev-1');
		expect(body.get('segment_id')).toBe('seg-1');
		expect((body.get('upload') as File).name).toBe('best.webm');
	});

	it('builds a streaming URL without fetching', () => {
		expect(api.mediaUrl('media-9')).toBe('/api/v1/media/media-9/content');
	});
});
