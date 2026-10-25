import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import { m } from '#lib/paraglide/messages.js';
import { session } from '#lib/session.svelte.ts';
import WebhookDialog from './WebhookDialog.svelte';

type Webhook = components['schemas']['WebhookOut'];

const fetchMock = vi.fn<(request: Request) => Promise<Response>>();
const sent: { method: string; path: string; body: unknown }[] = [];

function json(body: unknown, status = 200) {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'content-type': 'application/json' }
	});
}

const stored: Webhook = {
	id: 'hook',
	owner_id: 'anna',
	name: 'HA',
	url: 'http://ha.lan:8123/api/webhook/lekto',
	event_types: ['*'],
	active: true,
	signed: true,
	headers: ['Authorization'],
	body: 'thin',
	body_template: null,
	disabled_reason: null,
	failed_streak: 0,
	previous_secret_valid_until: null,
	created_at: '2026-10-25T10:00:00Z',
	updated_at: '2026-10-25T10:00:00Z'
};

beforeEach(() => {
	session.start({
		user: { id: 'anna', username: 'anna', role: 'user' },
		method: 'password',
		expires_at: '2026-10-26T12:00:00Z',
		csrf_token: 'token'
	});
	sent.length = 0;
	fetchMock.mockReset();
	fetchMock.mockImplementation(async (request) => {
		const path = new URL(request.url).pathname;
		const body = request.method === 'DELETE' ? null : await request.json().catch(() => null);
		sent.push({ method: request.method, path, body });
		if (request.method === 'POST' && path === '/api/v1/webhooks')
			return json({ ...stored, secret: null, signed: false }, 201);
		return json({ ...stored, signed: false });
	});
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	session.clear();
	vi.unstubAllGlobals();
});

describe('WebhookDialog', () => {
	it('creates an unsigned webhook with a header of its own', async () => {
		const oncreated = vi.fn();
		render(WebhookDialog, { open: true, onsaved: () => {}, oncreated });
		await userEvent.type(screen.getByLabelText(m.field_name()), 'HA');
		await userEvent.type(screen.getByLabelText(m.webhook_url()), stored.url);
		await userEvent.click(screen.getByRole('button', { name: m.webhook_header_add() }));
		await userEvent.type(screen.getByLabelText(m.webhook_header_name()), 'Authorization');
		const create = screen.getByRole('button', { name: m.create() });
		// A new header needs a value.
		expect((create as HTMLButtonElement).disabled).toBe(true);
		await userEvent.type(screen.getByLabelText(m.webhook_header_value()), 'Bearer t0ken');
		await userEvent.click(screen.getByLabelText(m.webhook_signed()));
		await userEvent.click(create);
		expect(sent).toEqual([
			{
				method: 'POST',
				path: '/api/v1/webhooks',
				body: {
					name: 'HA',
					url: stored.url,
					event_types: ['*'],
					active: true,
					signed: false,
					body: 'thin',
					body_template: null,
					headers: [{ name: 'Authorization', value: 'Bearer t0ken' }]
				}
			}
		]);
		expect(oncreated).toHaveBeenCalledOnce();
	});

	it('keeps untouched headers out of a change and stops signing', async () => {
		render(WebhookDialog, { open: true, webhook: stored, onsaved: () => {}, oncreated: () => {} });
		const value = await screen.findByLabelText(m.webhook_header_value());
		expect((value as HTMLInputElement).placeholder).toBe(m.webhook_header_kept());
		await userEvent.click(screen.getByLabelText(m.webhook_signed()));
		await userEvent.click(screen.getByRole('button', { name: m.save() }));
		expect(sent.map((item) => [item.method, item.path])).toEqual([
			['PATCH', '/api/v1/webhooks/hook'],
			['DELETE', '/api/v1/webhooks/hook/secret']
		]);
		expect(sent[0].body).not.toHaveProperty('headers');
	});

	it('sends all headers when one changes, an empty value keeping the stored one', async () => {
		render(WebhookDialog, { open: true, webhook: stored, onsaved: () => {}, oncreated: () => {} });
		await screen.findByLabelText(m.webhook_header_value());
		await userEvent.click(screen.getByRole('button', { name: m.webhook_header_add() }));
		const names = screen.getAllByLabelText(m.webhook_header_name());
		const values = screen.getAllByLabelText(m.webhook_header_value());
		await userEvent.type(names[1], 'X-Tenant');
		await userEvent.type(values[1], 'home');
		await userEvent.click(screen.getByRole('button', { name: m.save() }));
		expect((sent[0].body as { headers: unknown }).headers).toEqual([
			{ name: 'Authorization' },
			{ name: 'X-Tenant', value: 'home' }
		]);
	});

	it('sends a template body', async () => {
		render(WebhookDialog, { open: true, webhook: stored, onsaved: () => {}, oncreated: () => {} });
		await screen.findByLabelText(m.webhook_header_value());
		await userEvent.click(screen.getByRole('button', { name: m.webhook_body_template() }));
		expect(screen.getByText(m.webhook_body_template_hint())).toBeTruthy();
		const save = screen.getByRole('button', { name: m.save() });
		expect((save as HTMLButtonElement).disabled).toBe(true);
	});
});
