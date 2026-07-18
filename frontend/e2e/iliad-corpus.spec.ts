import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';

import { expect, test } from '@playwright/test';

const BACKEND = 'http://127.0.0.1:8643';
const COLLECTION = 'Iliad thus far';

test('provisioned Iliad 1.11–20 opens in the settled acquisition flow', async ({
	page,
	request
}) => {
	const collectionsResponse = await request.get(`${BACKEND}/api/v1/collections`);
	expect(collectionsResponse.ok()).toBe(true);
	const collections = (await collectionsResponse.json()) as Array<{
		id: string;
		name: string;
	}>;
	let collection = collections.find((item) => item.name === COLLECTION);
	if (!collection) {
		const created = await request.post(`${BACKEND}/api/v1/collections`, {
			data: { name: COLLECTION },
			headers: { 'Idempotency-Key': `e2e-iliad-collection-${Date.now()}` }
		});
		expect(created.ok()).toBe(true);
		collection = (await created.json()) as { id: string; name: string };
	}

	execFileSync(
		'uv',
		[
			'run',
			'python',
			'scripts/provision_iliad_11_20.py',
			'--base-url',
			BACKEND
		],
		{ cwd: resolve(process.cwd(), '../backend'), encoding: 'utf8' }
	);

	await page.goto(`/collections/${collection.id}`);
	await expect(page.getByRole('heading', { name: COLLECTION })).toBeVisible();
	await expect(page.getByRole('link', { name: 'Iliad 11-20' })).toBeVisible();
	await expect(page.locator('.badge.new')).toContainText('19');

	await page.getByRole('button', { name: '✦ Smart session' }).click();
	await expect(page).toHaveURL(/\/practice\/[\w-]+/);
	await expect(page.locator('.head-sub')).toContainText('Iliad 1.11–20');
	await expect(page.locator('.prompt .tag')).toHaveText('acquisition');
	await expect(page.getByText('1 · encounter')).toBeVisible();
	await expect(
		page.getByText(
			'Read the whole line once. Its annotations and reference audio are available before you retrieve it.'
		)
	).toBeVisible();
});
