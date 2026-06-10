import { expect, test } from '@playwright/test';

async function probe(page: import('@playwright/test').Page): Promise<string> {
	await page.goto('/');
	return page.evaluate(async () => {
		try {
			return await Promise.race([
				navigator.mediaDevices.getUserMedia({ audio: true }).then((s) => {
					const label = s.getAudioTracks()[0]?.label ?? 'no-track';
					s.getTracks().forEach((t) => t.stop());
					return `granted:${label}`;
				}),
				new Promise<string>((resolve) => setTimeout(() => resolve('timeout'), 4000))
			]);
		} catch (e) {
			return `error:${e instanceof Error ? e.name + ' ' + e.message : String(e)}`;
		}
	});
}

test('mic probe with default config permissions', async ({ page }) => {
	const result = await probe(page);
	console.log('MIC PROBE (default config):', result);
	expect(result).toContain('granted');
});
