import { describe, expect, it } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import { namedOptions, withChoice } from './options.ts';

describe('the options of a choice', () => {
	const contacts = namedOptions([
		{ id: 'c1', name: 'Stadtwerke' },
		{ id: 'c2', name: 'Bank' }
	]);

	it('start with "Choose" and list what there is', () => {
		expect(withChoice(contacts, '')).toEqual([
			{ value: '', label: m.rule_choose() },
			{ value: 'c1', label: 'Stadtwerke' },
			{ value: 'c2', label: 'Bank' }
		]);
		expect(withChoice(contacts, 'c2')).toHaveLength(3);
	});

	it('keep a current value the list does not have, labelled as unknown', () => {
		expect(withChoice(contacts, 'gone').at(-1)).toEqual({
			value: 'gone',
			label: m.rule_unknown()
		});
		expect(withChoice(contacts, 'closed', m.rule_space_unreachable()).at(-1)).toEqual({
			value: 'closed',
			label: m.rule_space_unreachable()
		});
	});
});
