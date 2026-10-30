import { render, screen, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { toast } from 'svelte-sonner';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { type IdentifierRow, kindLabel, row } from '#lib/identifiers.ts';
import type { Tag } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { phone } from '#lib/phone.svelte.ts';
import { calls, fakeApi } from '#lib/testing/documents.ts';
import { goTo, testPage } from '#lib/testing/page-state.svelte.ts';
import IdentifiersEditor from './IdentifiersEditor.svelte';

vi.mock('$app/navigation', async () => ({
	beforeNavigate: vi.fn(),
	goto: (await import('#lib/testing/page-state.svelte.ts')).fakeGoto
}));
vi.mock('$app/state', async () => ({
	page: (await import('#lib/testing/page-state.svelte.ts')).testPage
}));

const WORK = {
	id: 'p1',
	name: 'Arbeit',
	path: ['Arbeit'],
	parent_id: null,
	scope: 'topic',
	assignment: 'auto',
	shown: true,
	icon: null,
	color: 'violet',
	created_at: '2026-10-17T12:00:00Z'
} as Tag;

afterEach(() => phone.override(null));

function editor(rows: IdentifierRow[], extra: Record<string, unknown> = {}) {
	const props = $state({ rows, topics: [WORK], opened: null as number | null, ...extra });
	render(IdentifiersEditor, props);
	return props;
}

const line = (value: string | RegExp) => screen.getByRole('button', { name: value });

describe('IdentifiersEditor', () => {
	it('groups the identifiers by kind, one line each, and opens one at a time', async () => {
		const user = userEvent.setup();
		const props = editor([
			row('personnel_number', '4711', 'manual', 'p1'),
			row('iban', 'DE89370400440532013000', 'learned'),
			row('customer_number', 'KD-1', 'rejected')
		]);
		expect(
			screen.getByRole('heading', { name: `${kindLabel('personnel_number')} 1` })
		).toBeTruthy();
		expect(screen.getByRole('heading', { name: `${kindLabel('iban')} 1` })).toBeTruthy();
		const personnel = line(/^4711/);
		expect(within(personnel).getByText('Arbeit')).toBeTruthy();
		expect(within(line(/^DE89/)).getByText(m.identifier_learned())).toBeTruthy();
		expect(within(line(/^KD-1/)).getByText(m.identifier_rejected())).toBeTruthy();
		// Closed, the lines have no fields.
		expect(personnel.getAttribute('aria-expanded')).toBe('false');
		expect(screen.queryByLabelText(m.identifier_value())).toBeNull();
		await user.click(personnel);
		expect(personnel.getAttribute('aria-expanded')).toBe('true');
		const value = screen.getByLabelText(m.identifier_value()) as HTMLInputElement;
		expect(value.value).toBe('4711');
		await user.clear(value);
		await user.type(value, '0815{Enter}');
		// Enter closes the line; the change stays.
		expect(screen.queryByLabelText(m.identifier_value())).toBeNull();
		expect(props.rows[0].value).toBe('0815');
		// A learned one is taken over, a rejected one allowed again.
		await user.click(line(/^DE89/));
		expect(screen.getByText(m.identifier_learned_note())).toBeTruthy();
		await user.click(screen.getByRole('button', { name: m.identifier_keep() }));
		expect(props.rows[1].source).toBe('manual');
		await user.click(line(/^KD-1/));
		expect(line(/^DE89/).getAttribute('aria-expanded')).toBe('false');
		await user.click(screen.getByRole('button', { name: m.identifier_unblock() }));
		expect(props.rows.map((item) => item.value)).toEqual(['0815', 'DE89370400440532013000']);
	});

	it('adds one opened, ready to type, and removes it', async () => {
		const user = userEvent.setup();
		const props = editor([row('iban', 'DE89370400440532013000')]);
		await user.click(screen.getByRole('button', { name: m.identifier_add_short() }));
		expect(props.rows).toHaveLength(2);
		expect(document.activeElement).toBe(screen.getByLabelText(m.identifier_value()));
		expect(line(m.identifier_new()).getAttribute('aria-expanded')).toBe('true');
		await user.click(
			screen.getByRole('button', { name: m.identifier_remove_named({ value: m.identifier_new() }) })
		);
		expect(props.rows).toHaveLength(1);
	});

	it('finds identifiers by value written with spaces, by kind and by topic', async () => {
		const user = userEvent.setup();
		editor([
			row('personnel_number', '4711', 'manual', 'p1'),
			row('iban', 'DE89370400440532013000')
		]);
		const search = screen.getByLabelText(m.identifier_search());
		await user.type(search, 'arbeit');
		expect(screen.queryByRole('button', { name: /^DE89/ })).toBeNull();
		expect(line(/^4711/)).toBeTruthy();
		await user.clear(search);
		await user.type(search, 'DE89 3704');
		expect(screen.queryByRole('button', { name: /^4711/ })).toBeNull();
		await user.clear(search);
		await user.type(search, 'nichts');
		expect(screen.getByText(m.assignment_none_found())).toBeTruthy();
	});

	it('shows what the API refused in the open line', () => {
		const refused = row('iban', 'DE00 1234');
		editor([refused], {
			opened: refused.key,
			errors: { [refused.key]: "'DE00 1234' is not a valid IBAN" }
		});
		expect(screen.getByRole('alert').textContent).toContain('is not a valid IBAN');
		expect(screen.getByLabelText(m.identifier_value()).getAttribute('aria-invalid')).toBe('true');
	});

	it('says so when there is none, and adds with a round button on a phone', async () => {
		phone.override(true);
		const user = userEvent.setup();
		const props = editor([]);
		expect(screen.getByText(m.identifier_none())).toBeTruthy();
		await user.click(screen.getByRole('button', { name: m.identifier_add() }));
		expect(props.rows).toHaveLength(1);
	});
});

describe('IdentifiersEditor, where a learned one stands', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		goTo('/ui/inbox');
	});

	it('opens the documents that show it in the Beam, or says there are none', async () => {
		let places = [{ document_id: 'd1' }, { document_id: 'd2' }];
		const api = fakeApi({
			'POST /api/v1/identifiers/refs': async (request) => ({
				...(await request.json()),
				ref: 'REU4OQ'
			}),
			'GET /api/v1/identifiers/places/iban/REU4OQ': () => ({ places })
		});
		vi.stubGlobal('fetch', api);
		const info = vi.spyOn(toast, 'info');
		goTo('/ui/admin/master-data');
		const user = userEvent.setup();
		editor([row('iban', 'DE89370400440532013000', 'learned')]);
		await user.click(line(/^DE89/));
		await user.click(screen.getByRole('button', { name: m.identifier_whence() }));
		await vi.waitFor(() =>
			expect(testPage.state.beam).toMatchObject({
				ids: ['d1', 'd2'],
				index: 0,
				source: { kind: 'places', identifier: 'iban', ref: 'REU4OQ' }
			})
		);
		// The value went in a body, never into an address.
		expect(calls(api).some((call) => call.includes('DE89'))).toBe(false);
		places = [];
		goTo('/ui/admin/master-data');
		await user.click(screen.getByRole('button', { name: m.identifier_whence() }));
		await vi.waitFor(() => expect(info).toHaveBeenCalledWith(m.identifier_whence_none()));
		expect(testPage.state.beam).toBeUndefined();
	});
});
