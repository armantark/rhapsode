// Lightweight audiovisual feedback for the practice loop. Grounded in juicy-
// feedback research (CHI 2024, Kao et al.): what motivates is GRADED,
// success-DEPENDENT, audio-visually COHERENT feedback — not loud amplification,
// which can backfire by occluding the action→outcome link. So each rating gets
// a distinct character on a rising "better recall = brighter" scale, and a
// clean streak escalates to reward competence. Everything is synthesised on a
// lazily-created AudioContext (grading is a user gesture, satisfying autoplay
// policy); no audio files, no licensing. Muting persists in localStorage.
//
// Parked idea: swap the synth for curated recorded SFX if we ever want more
// fidelity — kept out for now to stay zero-dependency and small.

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

const GRADE_TONES: Record<AttemptRating, (streak: number) => void> = {
	// Again: a gentle two-note fall — "not yet", never a harsh buzzer.
	revealed: () => {
		tone(392, 0, 0.16, 'triangle');
		tone(294, 0.1, 0.2, 'triangle');
	},
	// Hard: a soft low "tock" — felt as effort/weight, quick decay.
	incorrect: () => tone(174.61, 0, 0.12, 'triangle'),
	// Good: a bright step up — clean confirmation.
	hesitant: () => {
		tone(440, 0, 0.13);
		tone(554.37, 0.08, 0.14);
	},
	// Easy: a sparkle arpeggio that climbs higher the longer the clean streak,
	// so a run of perfect recalls audibly rewards itself (competence/curiosity).
	clean: (streak) => {
		const lift = Math.min(streak, 5) * 40;
		tone(523.25 + lift, 0);
		tone(659.25 + lift, 0.06);
		tone(783.99 + lift, 0.12);
		if (streak >= 3) tone(1046.5 + lift, 0.18, 0.34);
	}
};

export function playGrade(rating: AttemptRating, streak = 0): void {
	if (!soundEnabled()) return;
	GRADE_TONES[rating](streak);
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
