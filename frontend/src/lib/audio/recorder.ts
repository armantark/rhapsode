/**
 * Browser-local attempt recording. Recordings live as in-memory blobs plus an
 * object URL for playback and are discarded unless the user explicitly saves
 * a best attempt (which uploads the blob as category "saved_best").
 */
export interface AttemptRecording {
	blob: Blob;
	url: string;
	mimeType: string;
	durationMs: number;
}

export function disposeRecording(recording: AttemptRecording | null): void {
	if (recording) URL.revokeObjectURL(recording.url);
}

function pickMimeType(): string {
	const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'];
	return candidates.find((type) => globalThis.MediaRecorder?.isTypeSupported?.(type)) ?? '';
}

export class Recorder {
	private stream: MediaStream | null = null;
	private recorder: MediaRecorder | null = null;
	private chunks: Blob[] = [];
	private startedAt = 0;

	get recording(): boolean {
		return this.recorder?.state === 'recording';
	}

	async start(): Promise<void> {
		this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
		const mimeType = pickMimeType();
		this.recorder = new MediaRecorder(this.stream, mimeType ? { mimeType } : undefined);
		this.chunks = [];
		this.recorder.ondataavailable = (event) => {
			if (event.data.size > 0) this.chunks.push(event.data);
		};
		this.startedAt = performance.now();
		this.recorder.start();
	}

	async stop(): Promise<AttemptRecording> {
		const recorder = this.recorder;
		if (!recorder) throw new Error('Recorder was not started.');
		const stopped = new Promise<void>((resolve) => {
			recorder.onstop = () => resolve();
		});
		recorder.stop();
		await stopped;
		const durationMs = Math.round(performance.now() - this.startedAt);
		const mimeType = recorder.mimeType || 'audio/webm';
		const blob = new Blob(this.chunks, { type: mimeType });
		this.releaseStream();
		return { blob, url: URL.createObjectURL(blob), mimeType, durationMs };
	}

	/** Stop tracks so the browser's mic indicator turns off between attempts. */
	releaseStream(): void {
		this.stream?.getTracks().forEach((track) => track.stop());
		this.stream = null;
		this.recorder = null;
	}
}
