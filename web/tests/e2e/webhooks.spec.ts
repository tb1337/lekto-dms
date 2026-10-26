// The webhook pages against a real API: a webhook is created on its own page (the secret shown
// once), opened, tested from its page, changed on its edit page and deleted from the list.
import { expect, test, type Page } from '@playwright/test';

const ADMIN = process.env.LEKTO_ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.LEKTO_ADMIN_PASSWORD ?? '';
const NAME = `e2e-webhook-${Date.now()}`;

test.beforeAll(() => {
	test.skip(!ADMIN_PASSWORD, 'LEKTO_ADMIN_PASSWORD is not set');
});

async function signIn(page: Page) {
	await page.goto('/ui/login');
	await page.getByLabel('Username').fill(ADMIN);
	await page.getByLabel('Password').fill(ADMIN_PASSWORD);
	await page.getByRole('button', { name: 'Sign in' }).click();
	await page.waitForURL('**/ui/inbox');
}

test('a webhook is created, tested, changed and deleted', async ({ page }) => {
	const problems: string[] = [];
	page.on('console', (message) => {
		if (message.type() === 'error' && !/status of [45]\d\d/.test(message.text()))
			problems.push(message.text());
	});
	page.on('pageerror', (error) => problems.push(error.message));
	await signIn(page);

	// Created on its own page, with a header of its own; the secret is shown once.
	await page.goto('/ui/webhooks');
	await page.getByRole('link', { name: 'New webhook' }).click();
	await page.waitForURL('**/ui/webhooks/new');
	await expect(page.getByRole('heading', { name: 'New webhook', level: 1 })).toBeVisible();
	const create = page.getByRole('button', { name: 'Create', exact: true });
	await expect(create).toBeDisabled();
	await page.getByRole('textbox', { name: 'Name', exact: true }).fill(NAME);
	await page.getByRole('textbox', { name: 'Target URL' }).fill('http://127.0.0.1:9/hook');
	await page.getByRole('button', { name: 'Add header' }).click();
	await page.getByLabel('Header name').fill('Authorization');
	await expect(create).toBeDisabled();
	await page.getByLabel('Header value').fill('Bearer t0ken');
	await create.click();
	await expect(page.getByTestId('secret')).toContainText('whsec_');
	await page.getByRole('button', { name: 'I have stored it' }).click();

	// The webhook's page: name, URL, deliveries. A test goes nowhere (port 9), its delivery shows.
	await page.waitForURL(/\/ui\/webhooks\/(?!new$)[^/]+$/);
	const url = page.url();
	await expect(page.getByRole('heading', { name: NAME, level: 1 })).toBeVisible();
	await expect(page.getByText('http://127.0.0.1:9/hook')).toBeVisible();
	await expect(page.getByText('No deliveries yet.')).toBeVisible();
	await page.getByRole('button', { name: 'Send test' }).click();
	await expect(page.getByText(/^Test failed/)).toBeVisible();
	await expect(page.getByRole('cell', { name: /Attempt 1/ })).toBeVisible();

	// Changed on the edit page: the stored header keeps its value, signing stops, a new name.
	await page.getByRole('link', { name: 'Edit' }).click();
	await page.waitForURL(`${url}/edit`);
	await expect(page.getByRole('heading', { name: `Edit ${NAME}`, level: 1 })).toBeVisible();
	await expect(page.getByLabel('Header value')).toHaveAttribute('placeholder', 'unchanged');
	await page.getByRole('textbox', { name: 'Name', exact: true }).fill(`${NAME} v2`);
	await page.getByRole('checkbox', { name: 'Sign requests' }).uncheck();
	await page.getByRole('button', { name: 'Save', exact: true }).click();
	await page.waitForURL(url);
	await expect(page.getByRole('heading', { name: `${NAME} v2`, level: 1 })).toBeVisible();
	await expect(page.getByText('Unsigned')).toBeVisible();

	// Cancelling the editor changes nothing.
	await page.getByRole('link', { name: 'Edit' }).click();
	await page.waitForURL(`${url}/edit`);
	await page.getByRole('textbox', { name: 'Name', exact: true }).fill('dropped');
	await page.getByRole('link', { name: 'Cancel' }).click();
	await page.waitForURL(url);
	await expect(page.getByRole('heading', { name: `${NAME} v2`, level: 1 })).toBeVisible();

	// Deleted on its page, then gone from the list.
	await page.getByRole('button', { name: `Delete ${NAME} v2` }).click();
	await page.getByRole('alertdialog').getByRole('button', { name: 'Delete' }).click();
	await page.waitForURL('**/ui/webhooks');
	await expect(page.getByText(`${NAME} v2`)).toHaveCount(0);

	expect(problems).toEqual([]);
});
