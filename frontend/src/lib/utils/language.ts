import type { LanguageProfile } from '$lib/api/types';

/** BCP-47 tags so browsers pick correct glyph shaping and line breaking. */
const LANG_CODES: Record<string, string> = {
	'ancient-greek': 'grc',
	'classical-armenian': 'xcl',
	latin: 'la',
	japanese: 'ja'
};

export function langCode(profile: Pick<LanguageProfile, 'slug'> | null | undefined): string {
	return profile ? (LANG_CODES[profile.slug] ?? profile.slug) : '';
}

export function fontStack(profile: Pick<LanguageProfile, 'fonts'> | null | undefined): string {
	const fonts = (profile?.fonts ?? []).map((font) => `'${font}'`);
	return [...fonts, 'var(--font-passage)'].join(', ');
}

export function supportsVertical(profile: LanguageProfile | null | undefined): boolean {
	return Boolean(profile?.display_options?.supports_vertical);
}

export function supportsRuby(profile: LanguageProfile | null | undefined): boolean {
	return Boolean(profile?.display_options?.supports_ruby);
}

/** Annotation layers a profile declares, e.g. translation/gloss/grammar. */
export function profileLayers(profile: LanguageProfile | null | undefined): { layer: string; label: string }[] {
	return (profile?.annotation_schemas ?? []).map((schema) => ({
		layer: String(schema.layer ?? ''),
		label: String(schema.label ?? schema.layer ?? '')
	}));
}

/**
 * Profiles can declare how a layer renders (Japanese: reading → ruby). Editor
 * annotations don't carry data, so the hint is attached at save time to match
 * the fixture shape ({"data": {"render": "ruby"}}).
 */
export function layerRenderData(
	profile: LanguageProfile | null | undefined,
	layer: string
): Record<string, unknown> | undefined {
	const schema = (profile?.annotation_schemas ?? []).find((candidate) => candidate.layer === layer);
	return typeof schema?.render === 'string' ? { render: schema.render } : undefined;
}
