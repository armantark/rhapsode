// Lightweight audiovisual feedback for the practice loop. The grade buttons
// are a physical, repeated gesture, so a short tuned tone plus a colour pulse
// makes each rating feel distinct and the session feel responsive — without
// pulling in an audio library or shipping sound files. Tones are synthesised
// on a lazily-created AudioContext (grading is a user gesture, so autoplay
// policy is satisfied) and can be muted; muting persists in localStorage.

import type { AttemptRating } from '$lib/api/types';

const SOUND_KEY = 'rhapsode.soundEnabled';

let context: AudioContext | null = null;

function soundEnabled(): boolean {
	if (typeof localStorage === 'undefined') return true;
	return localStorage.getItem(SOUND_KEY) !== 'false';
}

export function isSoundEnabled(): boolean {
	return soundEnabled();
}

export function setSoundEnabled(enabled: boolean): void {
	localStorage.setItem(SOUND_KEY, String(enabled));
}

function ctx(): AudioContext | null {
	if (typeof window === 'undefined') return null;
	const Ctor = window.AudioContext ?? (window as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
	if (!Ctor) return null;
	context ??= new Ctor();
	void context.resume();
	return context;
}

/** A short plucked note. Frequencies are chosen so the four grades form a
 *  rising scale from "Again" to "Easy" — the better you did, the higher and
 *  brighter the confirmation. */
function tone(freq: number, when: number, duration = 0.16, type: OscillatorType = 'sine'): void {
	const audio = ctx();
	if (!audio) return;
	const osc = audio.createOscillator();
	const gain = audio.createGain();
	osc.type = type;
	osc.frequency.value = freq;
	const start = audio.currentTime + when;
	gain.gain.setValueAtTime(0.0001, start);
	gain.gain.exponentialRampToValueAtTime(0.22, start + 0.012);
	gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
	osc.connect(gain).connect(audio.destination);
	osc.start(start);
	osc.stop(start + duration + 0.02);
}

const GRADE_TONES: Record<AttemptRating, () => void> = {
	revealed: () => tone(196, 0, 0.22, 'triangle'),
	incorrect: () => tone(261.63, 0, 0.18, 'triangle'),
	hesitant: () => tone(392, 0, 0.16),
	clean: () => {
		tone(523.25, 0);
		tone(783.99, 0.07);
	}
};

export function playGrade(rating: AttemptRating): void {
	if (!soundEnabled()) return;
	GRADE_TONES[rating]();
}

/** A rising major arpeggio to cap a finished session. */
export function playComplete(): void {
	if (!soundEnabled()) return;
	[523.25, 659.25, 783.99, 1046.5].forEach((freq, index) => tone(freq, index * 0.1, 0.3));
}

export function playUndo(): void {
	if (!soundEnabled()) return;
	tone(440, 0, 0.1, 'sine');
	tone(330, 0.06, 0.12, 'sine');
}
