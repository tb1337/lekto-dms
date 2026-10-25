import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { FieldDefinition, Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { newAction, newModel } from '#lib/rules/model.ts';
import { session } from '#lib/session.svelte.ts';
import ActionRow from './ActionRow.svelte';

const fields = [
	{ id: 'f1', name: 'Netto', key: 'netto', data_type: 'amount', document_type_ids: null }
] as unknown as FieldDefinition[];
const lookup = {
	contacts: [],
	documentTypes: [],
	tags: [],
	fields,
	spaces: [],
	users: []
} as unknown as Lookup;
const targets = [{ value: 'house', label: 'Haushalt' }];

afterEach(() => {
	session.clear();
	vi.unstubAllGlobals();
});

function fileInto(space: string) {
	const action = newAction('set_space');
	if (action.type === 'set_space') action.space_id = space;
	render(ActionRow, { action, lookup, targets, onremove: vi.fn() });
}

describe('filing into a space', () => {
	it('keeps a space the caller may not file into and says why saving needs another', () => {
		fileInto('closed');
		expect(screen.getByText(m.rule_space_unreachable_hint())).toBeTruthy();
	});

	it('says nothing about a space the caller files into', () => {
		fileInto('house');
		expect(screen.queryByText(m.rule_space_unreachable_hint())).toBeNull();
	});
});

describe('a template of an action', () => {
	it('names the fields of the rule without asking for them again', async () => {
		const fetchMock = vi.fn<(request: Request) => Promise<Response>>(async () =>
			Response.json({ used: [], rendered: null, missing: null, error: null, values: null })
		);
		vi.stubGlobal('fetch', fetchMock);
		const action = newAction('set_title');
		render(ActionRow, { action, lookup, targets, onremove: vi.fn() });
		await new Promise((resolve) => setTimeout(resolve, 0));
		const asked = fetchMock.mock.calls.map(([request]) => new URL(request.url).pathname);
		expect(asked).not.toContain('/api/v1/fields');
	});
});

describe('sending through a webhook', () => {
	function send(webhooks: Lookup['webhooks']) {
		session.start({
			user: { id: 'anna', username: 'anna', role: 'admin' },
			method: 'password',
			expires_at: '2026-10-26T12:00:00Z',
			csrf_token: 'token'
		});
		render(ActionRow, {
			action: newAction('send_webhook'),
			lookup: { ...lookup, webhooks },
			targets,
			onremove: vi.fn()
		});
	}

	it('offers only the webhooks of whoever saves the rule', () => {
		send([{ id: 'w1', name: 'Node-RED', owner_id: 'ben' }]);
		expect(screen.getByText(m.rule_send_webhook_none())).toBeTruthy();
	});

	it('explains what goes out through an own webhook', () => {
		send([{ id: 'w2', name: 'Home Assistant', owner_id: 'anna' }]);
		expect(screen.getByText(m.rule_send_webhook_hint())).toBeTruthy();
	});
});

describe('steps that ask and check', () => {
	it('asks with a name, a time in minutes and what happens without an answer', () => {
		const action = newAction('ask_webhook');
		render(ActionRow, { action, lookup, targets, onremove: vi.fn() });
		expect(screen.getByLabelText(m.rule_ask_name())).toBeTruthy();
		expect((screen.getByLabelText(m.rule_ask_timeout()) as HTMLInputElement).value).toBe('5');
		expect(screen.getByText(m.rule_ask_name_hint())).toBeTruthy();
	});

	it('checks what a step before brought', () => {
		const model = newModel();
		const action = newAction('condition');
		model.actions = [action];
		render(ActionRow, { action, lookup, targets, model, steps: ['flow'], onremove: vi.fn() });
		expect(screen.getByLabelText(m.rule_step_path())).toBeTruthy();
		expect(screen.getByText(m.rule_condition_step_hint())).toBeTruthy();
	});
});

describe('setting a field that is not text', () => {
	function setAmount(value: unknown) {
		const action = newAction('set_field');
		if (action.type === 'set_field') {
			action.field_id = 'f1';
			action.value = value as typeof action.value;
		}
		vi.stubGlobal(
			'fetch',
			vi.fn(async () =>
				Response.json({ used: [], rendered: null, missing: null, error: null, values: null })
			)
		);
		render(ActionRow, { action, lookup, targets, onremove: vi.fn() });
		return action;
	}

	it('switches between a fixed value and a template, carrying the value over', async () => {
		const user = userEvent.setup();
		const action = setAmount({ amount: '12.50', currency: 'EUR' });
		const fixed = screen.getByRole('button', { name: m.rule_value_fixed() });
		expect(fixed.getAttribute('aria-pressed')).toBe('true');
		expect(screen.queryByRole('button', { name: m.template_editor_open() })).toBeNull();

		await user.click(screen.getByRole('button', { name: m.rule_value_template() }));
		// The page holds its model in state; here the action is plain: only the value changes.
		expect(action).toMatchObject({ value: '12.50 EUR', templated: true });

		await user.click(screen.getByRole('button', { name: m.rule_value_fixed() }));
		expect(action).toMatchObject({ value: { amount: '12.50', currency: 'EUR' }, templated: false });
	});

	it('opens a value given as text as a template', () => {
		setAmount('{{ steps.erp.total }} EUR');
		const template = screen.getByRole('button', { name: m.rule_value_template() });
		expect(template.getAttribute('aria-pressed')).toBe('true');
		expect(screen.getByRole('button', { name: m.template_editor_open() })).toBeTruthy();
	});
});
