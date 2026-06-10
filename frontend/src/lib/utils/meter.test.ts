import { describe, expect, it } from 'vitest';
import { syllableSpans } from './meter';

describe('syllableSpans', () => {
	it('slices a Greek word into syllables and assigns marks', () => {
		const spans = syllableSpans('Μῆνιν', [
			{ text: 'μῆ', length: 'long' },
			{ text: 'νιν', length: 'short' }
		]);
		expect(spans).toEqual([
			{ text: 'Μῆ', mark: '—' },
			{ text: 'νιν', mark: '◡' }
		]);
	});

	it('survives edition differences: macrons and attached punctuation', () => {
		// Token text carries a combining macron and a trailing comma that the
		// scansion source lacks; letters still align one-to-one.
		const spans = syllableSpans('θεὰ̄,', [
			{ text: 'θε', length: 'short' },
			{ text: 'ὰ', length: 'long' }
		]);
		expect(spans?.map((span) => span.text).join('')).toBe('θεὰ̄,');
		expect(spans?.map((span) => span.mark)).toEqual(['◡', '—']);
	});

	it('keeps the elision apostrophe on the final syllable', () => {
		const spans = syllableSpans('ἄλγε᾽', [
			{ text: 'ἄλ', length: 'long' },
			{ text: 'γε', length: 'short' }
		]);
		expect(spans?.[1].text).toBe('γε᾽');
	});

	it('returns null when letter counts cannot align', () => {
		expect(syllableSpans('Μῆνιν', [{ text: 'μῆνιντος', length: 'long' }])).toBeNull();
		expect(syllableSpans('Μῆ', [
			{ text: 'μῆ', length: 'long' },
			{ text: 'νιν', length: 'short' }
		])).toBeNull();
	});
});
