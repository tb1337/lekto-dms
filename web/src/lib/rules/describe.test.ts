import { describe, expect, it } from 'vitest';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { actionTemplate, operatorLabel } from './describe.ts';

function textField(id: string, name: string, data_type: string) {
	return {
		id,
		name,
		key: name.toLowerCase(),
		data_type,
		document_type_ids: null,
		choices: [],
		required: false,
		required_document_type_ids: [],
		description: null,
		created_at: '2026-10-13T12:00:00Z'
	};
}

const lookup = {
	contacts: [],
	documentTypes: [],
	tags: [],
	spaces: [],
	fields: [textField('f1', 'Notiz', 'text'), textField('f2', 'Betrag', 'amount')]
} as unknown as Lookup;

describe('the template of an action', () => {
	it('is the title, the review reason and a text field value', () => {
		expect(actionTemplate({ type: 'set_title', template: '{{ contact }}' }, lookup)).toEqual({
			lead: `${m.rule_action_set_title()}: `,
			template: '{{ contact }}'
		});
		expect(actionTemplate({ type: 'force_review', reason: 'Prüfen' }, lookup)?.template).toBe(
			'Prüfen'
		);
		expect(
			actionTemplate({ type: 'set_field', field_id: 'f1', value: '{{ title }}' }, lookup)
		).toEqual({ lead: `${m.rule_action_set_field()}: Notiz = `, template: '{{ title }}' });
	});

	it('is absent from other actions and other fields', () => {
		const amount = { amount: '1.00', currency: 'EUR' };
		expect(actionTemplate({ type: 'set_field', field_id: 'f2', value: amount }, lookup)).toBeNull();
		expect(actionTemplate({ type: 'add_tags', tag_ids: [] }, lookup)).toBeNull();
	});
});

describe('operators in the words of a period', () => {
	it('starts after, ends before, overlaps', () => {
		expect(operatorLabel('field', 'gt', 'period')).toBe(m.rule_op_period_gt());
		expect(operatorLabel('field', 'lt', 'period')).toBe(m.rule_op_period_lt());
		expect(operatorLabel('field', 'overlaps', 'period')).toBe(m.rule_op_overlaps());
		expect(operatorLabel('field', 'gt', 'date')).toBe(m.rule_op_date_gt());
	});
});
