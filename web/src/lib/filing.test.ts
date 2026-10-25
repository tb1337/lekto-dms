import { describe, expect, it } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import {
	confirmHint,
	filingKind,
	initialChoice,
	memberChips,
	openFiling,
	openSpaceCheck,
	readersLaterText,
	visibleText,
	whereText
} from '#lib/filing.ts';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';

type Check = components['schemas']['FieldCheckOut'];
type Member = components['schemas']['SpaceOut']['members'][number];

const TOBI = 'u-tobi';
const ANNA = 'u-anna';
const MINE = 's-mine';
const ANNAS = 's-anna';
const HOME = 's-home';

const lookup = {
	spaces: [
		{
			id: MINE,
			name: 'Personal',
			personal_of: TOBI,
			role: 'edit',
			members: [{ user_id: TOBI, role: 'edit', username: 'tobi' }]
		},
		{
			id: HOME,
			name: 'Haushalt',
			personal_of: null,
			role: 'edit',
			members: [
				{ user_id: TOBI, role: 'edit', username: 'tobi' },
				{ user_id: ANNA, role: 'read', username: 'anna', display_name: 'Anna Leider' }
			]
		}
	],
	users: [
		{ id: TOBI, username: 'tobi', role: 'user', personal_space_id: MINE },
		{
			id: ANNA,
			username: 'anna',
			display_name: 'Anna Leider',
			role: 'user',
			personal_space_id: ANNAS
		}
	]
} as unknown as Lookup;

const tobi = { id: TOBI, admin: false };
const choices = [{ value: HOME }, { value: ANNAS }];

function spaceCheck(fields: Partial<Check>): Check {
	return {
		field: 'space',
		outcome: 'uncertain',
		confidence: 0.89,
		reason: null,
		proposed: null,
		evidence: null,
		value: null,
		suggestion: null,
		new_name: null,
		...fields
	} as Check;
}

describe('filing', () => {
	it('finds the open space check among the open nodes', () => {
		const check = spaceCheck({});
		expect(
			openSpaceCheck([{ node: 'judge', outcome: 'uncertain', reason: null, fields: [check] }])
		).toBe(check);
		expect(openSpaceCheck([])).toBeNull();
	});

	it('tells staying, moving and handing over apart', () => {
		expect(filingKind(MINE, MINE, lookup, tobi)).toBe('stay');
		expect(filingKind(HOME, MINE, lookup, tobi)).toBe('move');
		expect(filingKind(ANNAS, MINE, lookup, tobi)).toBe('hand_over');
	});

	it('offers the suggestion first, the other spaces named, and staying, each once', () => {
		const filing = openFiling(
			spaceCheck({
				suggestion: ANNAS,
				candidates: [
					{
						value: MINE,
						label: '',
						contradicted: true,
						sources: [{ signal: 'signal_neighbours', names: true, votes: 5, found: 5 }]
					},
					{
						value: ANNAS,
						label: '',
						contradicted: true,
						sources: [{ signal: 'signal_llm', names: true, recipient: true }]
					}
				] as Check['candidates']
			}),
			MINE,
			lookup,
			tobi,
			choices
		);
		expect(filing.options.map((option) => [option.value, option.kind])).toEqual([
			[ANNAS, 'hand_over'],
			[MINE, 'stay']
		]);
		expect(filing.lead).toBe(m.filing_lead_hand_over({ name: 'Anna Leider' }));
		expect(filing.options[0].chips.map((chip) => chip.text)).toEqual([
			m.filing_chip_recipient({ name: 'Anna Leider' }),
			m.filing_chip_model()
		]);
		expect(filing.options[1].title).toBe(m.filing_stay({ space: m.space_personal() }));
		expect(initialChoice(filing)).toBe(ANNAS);
	});

	it('chooses nothing when the signals disagree or the suggestion is not the caller’s to take', () => {
		const disagreeing = openFiling(
			spaceCheck({
				candidates: [
					{ value: HOME, label: '', contradicted: true, sources: [] },
					{ value: MINE, label: '', contradicted: true, sources: [] }
				] as Check['candidates']
			}),
			MINE,
			lookup,
			tobi,
			choices
		);
		expect(disagreeing.disagree).toBe(true);
		expect(initialChoice(disagreeing)).toBe('');
		const unavailable = openFiling(spaceCheck({ suggestion: HOME }), MINE, lookup, tobi, []);
		expect(unavailable.options[0].choosable).toBe(false);
		expect(initialChoice(unavailable)).toBe('');
	});

	it('says what each choice does above "Confirm"', () => {
		expect(confirmHint('', MINE, lookup, tobi)).toEqual({
			text: m.filing_choose_first(),
			tone: 'hint'
		});
		expect(confirmHint(MINE, MINE, lookup, tobi)).toBeNull();
		expect(confirmHint(ANNAS, MINE, lookup, tobi)).toEqual({
			text: m.filing_hint_hand_over({ name: 'Anna Leider' }),
			tone: 'warning'
		});
		expect(confirmHint(ANNAS, MINE, lookup, { id: TOBI, admin: true })?.text).toBe(
			m.filing_hint_hand_over_admin({ name: 'Anna Leider' })
		);
		expect(confirmHint(HOME, MINE, lookup, tobi)).toEqual({
			text: m.filing_hint_move_readers({ space: 'Haushalt', names: 'Anna Leider' }),
			tone: 'hint'
		});
	});

	it('reads another person’s space as theirs', () => {
		const admin = { id: 'u-admin', admin: true };
		const filing = openFiling(spaceCheck({}), MINE, lookup, admin, []);
		expect(filing.options[0].title).toBe(m.filing_stay_with({ name: 'tobi' }));
		expect(whereText(MINE, lookup, admin, true)).toBe(
			m.filing_where_person({ name: 'tobi', visible: m.visible_to({ names: 'tobi' }) })
		);
		expect(confirmHint(ANNAS, HOME, lookup, { id: TOBI, admin: false })?.tone).toBe('warning');
	});

	it('lists the members, the caller first, readers once the document is green', () => {
		const home = lookup.spaces[1].members;
		expect(memberChips(home, tobi, true)).toEqual([
			{ key: TOBI, text: m.filing_you_edit() },
			{ key: ANNA, text: m.filing_member_read({ name: 'Anna Leider' }) }
		]);
		expect(memberChips(home, tobi, false)).toEqual([
			{ key: TOBI, text: m.filing_you_edit() },
			{ key: ANNA, text: m.filing_member_read_later({ name: 'Anna Leider' }) }
		]);
		expect(whereText(MINE, lookup, tobi, true)).toBe(
			m.filing_where({ space: m.space_personal(), visible: m.visible_to_you() })
		);
	});

	it('keeps two members of one display name apart', () => {
		const twins = [
			{ user_id: TOBI, role: 'edit', username: 'tobi' },
			{ user_id: 'u-anna-1', role: 'read', username: 'anna1', display_name: 'Anna' },
			{ user_id: 'u-anna-2', role: 'read', username: 'anna2', display_name: 'Anna' }
		] as unknown as Member[];
		const chips = memberChips(twins, tobi, true);
		expect(chips.map((chip) => chip.text)).toEqual([
			m.filing_you_edit(),
			m.filing_member_read({ name: 'Anna' }),
			m.filing_member_read({ name: 'Anna' })
		]);
		expect(new Set(chips.map((chip) => chip.key)).size).toBe(3);
	});

	it('says who sees the document now and who once it is green', () => {
		const home = lookup.spaces[1].members;
		expect(visibleText(home, tobi, true)).toBe(m.visible_to({ names: 'Anna Leider' }));
		expect(visibleText(home, tobi, false)).toBe(m.visible_to_you());
		expect(readersLaterText(home, tobi, false)).toBe(
			m.visible_to_readers_later({ names: 'Anna Leider' })
		);
		expect(readersLaterText(home, tobi, true)).toBeNull();
	});
});
