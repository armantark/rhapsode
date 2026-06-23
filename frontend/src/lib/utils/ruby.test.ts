import { describe, expect, it } from 'vitest';
import japaneseFixture from '../../../../contracts/fixtures/japanese-passage.json';
import { japaneseRubyParts, rubyReading, textLayers } from './ruby';

// Mirror the committed fixture: a reading annotation flagged render=ruby plus
// a plain translation layer.
const fixtureSegment = {
	annotations: japaneseFixture.segments[0].annotations.map((annotation, index) => ({
		id: `ann-${index}`,
		segment_id: 'seg-1',
		layer: annotation.layer,
		value: annotation.value,
		data: (annotation as { data?: Record<string, unknown> }).data ?? {}
	}))
};

describe('rubyReading', () => {
	it('finds the fixture reading flagged for ruby rendering', () => {
		expect(rubyReading(fixtureSegment)).toBe('ぎおんしょうじゃのかねのこえ');
	});

	it('ignores reading layers without the ruby flag', () => {
		const segment = {
			annotations: [
				{ id: 'a', segment_id: 's', layer: 'reading', value: 'plain', data: {} }
			]
		};
		expect(rubyReading(segment)).toBeNull();
	});
});

describe('textLayers', () => {
	it('returns enabled layers but never the ruby-rendered reading', () => {
		expect(textLayers(fixtureSegment, ['translation', 'reading'])).toEqual([
			{ layer: 'translation', value: 'The sound of the bells of Gion Shōja' }
		]);
	});

	it('returns nothing when no layers are enabled', () => {
		expect(textLayers(fixtureSegment, [])).toEqual([]);
	});
});

describe('japaneseRubyParts', () => {
	it('ignores kana-only readings from older annotations', () => {
		expect(japaneseRubyParts('ふたつの', 'ふたつの')).toEqual([
			{ text: 'ふたつの', reading: null }
		]);
	});

	it('puts ruby only over kanji inside mixed kana/kanji tokens', () => {
		expect(japaneseRubyParts('こぼれ落ちた', 'こぼれおちた')).toEqual([
			{ text: 'こぼれ', reading: null },
			{ text: '落', reading: 'お' },
			{ text: 'ちた', reading: null }
		]);
		expect(japaneseRubyParts('引き合う', 'ひきあう')).toEqual([
			{ text: '引', reading: 'ひ' },
			{ text: 'き', reading: null },
			{ text: '合', reading: 'あ' },
			{ text: 'う', reading: null }
		]);
	});
});
