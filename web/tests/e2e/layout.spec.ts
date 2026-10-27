// The layout rules of web/DESIGN.md in a browser, for every area at a phone's, a laptop's and a
// desktop's width: nothing scrolls sideways, every control is a finger's size on the phone (44
// pixels, a larger invisible hit area counts) and at least 24 pixels wider, and no page logs an
// error. Signs in as the admin of the environment, as `areas.spec.ts` does.
import { expect, test, type Page } from '@playwright/test';

const ADMIN = process.env.LEKTO_ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.LEKTO_ADMIN_PASSWORD ?? '';

const PATHS = [
	'/ui/',
	'/ui/inbox',
	'/ui/documents',
	'/ui/spaces',
	'/ui/rules',
	'/ui/rules/new',
	'/ui/webhooks',
	'/ui/webhooks/new',
	'/ui/system',
	'/ui/admin/master-data',
	'/ui/admin/users',
	'/ui/settings'
];

const WIDTHS = [
	{ name: 'phone', width: 390, height: 844, target: 44 },
	{ name: 'laptop', width: 1024, height: 768, target: 24 },
	{ name: 'desktop', width: 1440, height: 900, target: 24 }
];

/** What sticks out sideways, and the controls smaller than `target` (with their hit area). */
async function measure(page: Page, target: number) {
	return page.evaluate((target) => {
		const width = window.innerWidth;
		const overflow = document.documentElement.scrollWidth - width;
		const small: string[] = [];
		const controls = document.querySelectorAll<HTMLElement>(
			'a[href], button, [role="button"], input:not([type="hidden"]), select, textarea, [role="switch"], [role="combobox"]'
		);
		const px = (value: string) => (value.endsWith('px') ? parseFloat(value) : 0);
		for (const element of controls) {
			const box = element.getBoundingClientRect();
			if (box.width === 0 || box.height === 0) continue;
			if (element.closest('[aria-hidden="true"], .sr-only, [data-inline], p, dd')) continue;
			let [w, h] = [box.width, box.height];
			// A field inside its label or its frame (the search box, the date input; no taller than a
			// field) takes the pointer on the whole of it.
			if (element.matches('input, select, textarea')) {
				const parent = element.parentElement;
				const frame =
					element.closest('label') ??
					(parent &&
					parent.querySelectorAll('a[href], button, input, select, textarea').length === 1 &&
					parent.getBoundingClientRect().height <= 64
						? parent
						: null);
				if (frame) {
					const outer = frame.getBoundingClientRect();
					[w, h] = [Math.max(w, outer.width), Math.max(h, outer.height)];
				}
			}
			// A larger invisible hit area (`after:absolute after:-inset-*`) counts: around the
			// element when it is positioned, else around the box it is placed in.
			const after = getComputedStyle(element, '::after');
			if (after.position === 'absolute' && after.content !== 'none') {
				const placed = getComputedStyle(element).position !== 'static';
				const base = placed ? box : (element.offsetParent?.getBoundingClientRect() ?? box);
				w = Math.max(w, base.width - px(after.left) - px(after.right));
				h = Math.max(h, base.height - px(after.top) - px(after.bottom));
			}
			if (w + 0.5 < target || h + 0.5 < target) {
				const name = (element.getAttribute('aria-label') ?? element.textContent ?? '').trim();
				small.push(
					`${element.tagName.toLowerCase()} ${Math.round(w)}×${Math.round(h)} ${name.slice(0, 40)}`
				);
			}
		}
		return { overflow, small };
	}, target);
}

test.beforeEach(() => {
	test.skip(!ADMIN_PASSWORD, 'LEKTO_ADMIN_PASSWORD is not set');
});

for (const size of WIDTHS) {
	test(`every area holds the layout rules at ${size.width} px`, async ({ browser }) => {
		const context = await browser.newContext({
			viewport: { width: size.width, height: size.height },
			hasTouch: size.name === 'phone'
		});
		const page = await context.newPage();
		const problems: string[] = [];
		page.on('console', (message) => {
			// Missing services (search, models) answer 4xx/5xx on purpose; those are not page errors.
			if (message.type() === 'error' && !/status of [45]\d\d/.test(message.text()))
				problems.push(message.text());
		});
		page.on('pageerror', (error) => problems.push(error.message));

		await page.goto('/ui/login');
		await page.getByLabel('Username').fill(ADMIN);
		await page.getByLabel('Password').fill(ADMIN_PASSWORD);
		await page.getByRole('button', { name: 'Sign in' }).click();
		await page.waitForURL('**/ui/');

		const findings: string[] = [];
		for (const path of PATHS) {
			await page.goto(path);
			await page.waitForLoadState('networkidle');
			const { overflow, small } = await measure(page, size.target);
			if (overflow > 1) findings.push(`${path}: ${overflow} px wider than the window`);
			for (const control of small) findings.push(`${path}: ${control}`);
		}
		// The navigation sheet of the phone does not scroll sideways either.
		if (size.name === 'phone') {
			await page.getByRole('button', { name: 'Open navigation' }).click();
			const sheet = page.locator('[data-slot="sheet-content"]');
			await sheet.waitFor();
			const wider = await sheet.evaluate((element) => element.scrollWidth - element.clientWidth);
			if (wider > 1) findings.push(`navigation sheet: ${wider} px wider than itself`);
		}
		expect(findings).toEqual([]);
		expect(problems).toEqual([]);
		await context.close();
	});
}
