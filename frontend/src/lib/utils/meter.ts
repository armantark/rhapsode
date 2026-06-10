/**
 * Align scanned syllables onto a token's own text so quantity marks render
 * OVER the syllables they govern (ruby), not as a detached label.
 *
 * The scansion source and the practiced edition disagree on macrons, accents,
 * and attached punctuation, so we never display the source's syllable text.
 * Instead we count base letters per scanned syllable and slice the token's
 * text into spans with the same letter counts — diacritics ride along with
 * their base letter and trailing punctuation sticks to the last syllable.
 */

export interface MeterSyllable {
	text: string;
	// "long" | "short" | "continuation" — a continuation is the tail of a
	// syllable that started on the previous token (elision across words);
	// its mark already appeared at the syllable's onset.
	length: string;
}

export interface SyllableSpan {
	text: string;
	mark: string;
}

const LONG_MARK = '—';
const SHORT_MARK = '◡';

function baseLetterCount(text: string): number {
	let count = 0;
	for (const char of text.normalize('NFD')) {
		if (/\p{L}/u.test(char)) count += 1;
	}
	return count;
}

/** Null when the token text can't be aligned (counts disagree); callers fall
 * back to showing the compact mark string under the word instead. */
export function syllableSpans(tokenText: string, syllables: MeterSyllable[]): SyllableSpan[] | null {
	if (!syllables.length) return null;
	const chars = [...tokenText.normalize('NFD')];
	let position = 0;
	const spans: SyllableSpan[] = [];
	for (const syllable of syllables) {
		const target = baseLetterCount(syllable.text);
		if (target === 0) return null;
		let letters = 0;
		const start = position;
		while (position < chars.length && letters < target) {
			if (/\p{L}/u.test(chars[position])) letters += 1;
			position += 1;
		}
		if (letters < target) return null;
		// Combining marks belong to the letter they follow.
		while (position < chars.length && /\p{M}/u.test(chars[position])) position += 1;
		spans.push({
			text: chars.slice(start, position).join('').normalize('NFC'),
			mark:
				syllable.length === 'long' ? LONG_MARK : syllable.length === 'short' ? SHORT_MARK : ''
		});
	}
	// Elision apostrophes and punctuation trail the final syllable.
	if (position < chars.length) {
		const rest = chars.slice(position).join('');
		if (/\p{L}/u.test(rest)) return null;
		spans[spans.length - 1].text += rest.normalize('NFC');
	}
	return spans;
}
