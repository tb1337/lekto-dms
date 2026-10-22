import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import { session } from '#lib/session.svelte.ts';
import ProfileForm from './ProfileForm.svelte';

const fetchMock = vi.fn<(request: Request) => Promise<Response>>();
const sent: { path: string; body: unknown }[] = [];

function json(body: unknown, status = 200) {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'content-type': 'application/json' }
	});
}

const stored = {
	user_id: 'anna',
	display_name: 'Anna Example',
	aliases: ['Anna Sample'],
	birth_date: '1980-06-15',
	email: 'anna@mail.example',
	identifiers: [{ kind: 'tax_id', value: '12345678911' }]
};

beforeEach(() => {
	session.start({
		user: { id: 'anna', username: 'anna', role: 'user' },
		method: 'password',
		expires_at: '2026-10-14T12:00:00Z',
		csrf_token: 'token'
	});
	sent.length = 0;
	fetchMock.mockReset();
	fetchMock.mockImplementation(async (request) => {
		const path = new URL(request.url).pathname;
		if (request.method === 'PATCH') {
			const body = await request.json();
			sent.push({ path, body });
			return json({ ...stored, ...body });
		}
		if (path.endsWith('/profile')) return json(stored);
		return json([]);
	});
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	session.clear();
	vi.unstubAllGlobals();
});

describe('ProfileForm', () => {
	it('shows the own profile and saves what is in it', async () => {
		render(ProfileForm);
		const name = await screen.findByLabelText(m.profile_display_name());
		expect((name as HTMLInputElement).value).toBe('Anna Example');
		expect(screen.getByText('Anna Sample')).toBeTruthy();
		expect(screen.getByText('12345678911')).toBeTruthy();
		await userEvent.click(
			screen.getByRole('button', { name: m.profile_alias_remove({ name: 'Anna Sample' }) })
		);
		await userEvent.type(screen.getByLabelText(m.profile_aliases()), 'Anna Muster{Enter}');
		await userEvent.clear(name);
		await userEvent.click(screen.getByRole('button', { name: m.save() }));
		expect(sent).toEqual([
			{
				path: '/api/v1/auth/me/profile',
				body: {
					display_name: null,
					aliases: ['Anna Muster'],
					birth_date: '1980-06-15',
					email: 'anna@mail.example',
					identifiers: [{ kind: 'tax_id', value: '12345678911' }]
				}
			}
		]);
	});

	it('edits another user’s profile for an admin', async () => {
		render(ProfileForm, { userId: 'bob' });
		await screen.findByLabelText(m.profile_display_name());
		await userEvent.click(screen.getByRole('button', { name: m.save() }));
		expect(sent.map((item) => item.path)).toEqual(['/api/v1/users/bob/profile']);
	});
});
