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

test.describe('no context permissions', () => {
	test.use({ permissions: [] });
	test('probe A', async ({ page }) => {
		console.log('PROBE A (no permissions):', await probe(page));
	});
});

test.describe('headful', () => {
	test.use({ headless: false });
	test('probe B', async ({ page }) => {
		console.log('PROBE B (headful):', await probe(page));
	});
});

test('probe C default', async ({ page }) => {
	console.log('PROBE C (default config):', await probe(page));
	expect(true).toBe(true);
});
