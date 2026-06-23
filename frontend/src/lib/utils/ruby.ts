import type { Segment } from '$lib/api/types';

export interface RubyPart {
	text: string;
	reading: string | null;
}

/**
 * A "reading" annotation flagged with data.render === "ruby" covers the
 * segment it is attached to. Japanese prep can attach readings to token
 * children, while older passages can still use one whole-line reading.
 */
export function rubyReading(segment: Pick<Segment, 'annotations'>): string | null {
	const annotation = (segment.annotations ?? []).find(
		(candidate) => candidate.layer === 'reading' && candidate.data?.render === 'ruby'
	);
	return annotation?.value ?? null;
}

export function japaneseRubyParts(text: string, reading: string): RubyPart[] {
	if (!hasKanji(text)) return [{ text, reading: null }];
	const chars = [...text];
	const readingChars = [...reading];
	const parts: RubyPart[] = [];
	let index = 0;
	let readingIndex = 0;

	while (index < chars.length) {
		const char = chars[index];
		if (!isKanji(char)) {
			parts.push({ text: char, reading: null });
			if (toHiragana(char) === readingChars[readingIndex]) readingIndex += 1;
			index += 1;
			continue;
		}

		let kanjiEnd = index + 1;
		while (kanjiEnd < chars.length && isKanji(chars[kanjiEnd])) kanjiEnd += 1;
		const nextKana = followingKana(chars, kanjiEnd);
		const rubyEnd = nextKana
			? findReadingBoundary(readingChars, readingIndex, nextKana)
			: readingChars.length;
		const ruby = readingChars.slice(readingIndex, rubyEnd).join('');
		parts.push({ text: chars.slice(index, kanjiEnd).join(''), reading: ruby || null });
		readingIndex = rubyEnd;
		index = kanjiEnd;
	}
	return coalescePlain(parts);
}

/** Layers worth showing as text rows (ruby readings render inline instead). */
export function textLayers(segment: Pick<Segment, 'annotations'>, enabled: string[]): { layer: string; value: string }[] {
	return (segment.annotations ?? [])
		.filter((annotation) => enabled.includes(annotation.layer))
		.filter((annotation) => annotation.data?.render !== 'ruby')
		.map(({ layer, value }) => ({ layer, value }));
}

function hasKanji(text: string): boolean {
	return [...text].some(isKanji);
}

function isKanji(char: string): boolean {
	return char >= '\u3400' && char <= '\u9fff';
}

function isKana(char: string): boolean {
	return (char >= '\u3041' && char <= '\u3096') || (char >= '\u30a1' && char <= '\u30f6');
}

function toHiragana(char: string): string {
	return char >= '\u30a1' && char <= '\u30f6' ? String.fromCodePoint(char.codePointAt(0)! - 0x60) : char;
}

function followingKana(chars: string[], start: number): string[] {
	const kana: string[] = [];
	for (let index = start; index < chars.length && isKana(chars[index]); index += 1) {
		kana.push(toHiragana(chars[index]));
	}
	return kana;
}

function findReadingBoundary(reading: string[], start: number, nextKana: string[]): number {
	if (!nextKana.length) return reading.length;
	for (let index = start; index <= reading.length - nextKana.length; index += 1) {
		if (nextKana.every((char, offset) => reading[index + offset] === char)) return index;
	}
	return reading.length;
}

function coalescePlain(parts: RubyPart[]): RubyPart[] {
	const coalesced: RubyPart[] = [];
	for (const part of parts) {
		const previous = coalesced.at(-1);
		if (previous && !previous.reading && !part.reading) {
			previous.text += part.text;
		} else {
			coalesced.push({ ...part });
		}
	}
	return coalesced;
}
