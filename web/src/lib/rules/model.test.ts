import { describe, expect, it } from 'vitest';
import { ApiError } from '#lib/api/problem.ts';
import { keyAt, saveErrors } from './errors.ts';
import {
	FIELD_TYPE_OPERATORS,
	CONDITION_FIELD_OPERATORS,
	LIMITS,
	asFixed,
	asTemplate,
	isTemplated,
	canAddGroup,
	changeField,
	changeConditionField,
	changeOperator,
	conditionsOf,
	fromApi,
	move,
	newAction,
	newCondition,
	newGroup,
	newModel,
	referencedIds,
	toApi,
	validate,
	type ApiCondition,
	type ApiDefinition,
	type ApiGroup,
	type FieldInfo,
	type ConditionNode,
	type GroupNode,
	type RuleModel
} from './model.ts';

const failed = (status: number, detail: string, spaceId: string | null = null) =>
	new ApiError(
		status,
		{
			type: 'about:blank',
			title: 'Failed',
			status,
			detail,
			existing_document_id: null,
			space_id: spaceId,
			open_fields: null,
			blocking_spaces: null,
			second_factor_required: null,
			reason: null,
			errors: null
		},
		null
	);

const ID = (n: number) => `01999d5e-${String(n).padStart(4, '0')}-7c1e-b6a3-2f4d5e6f7a8b`;

const FIELDS: FieldInfo[] = [
	{ id: ID(101), data_type: 'text', choices: [] },
	{ id: ID(102), data_type: 'link', choices: [] },
	{ id: ID(103), data_type: 'number', choices: [] },
	{ id: ID(104), data_type: 'amount', choices: [] },
	{ id: ID(105), data_type: 'date', choices: [] },
	{ id: ID(106), data_type: 'boolean', choices: [] },
	{ id: ID(107), data_type: 'choice', choices: ['monthly', 'yearly'] },
	{ id: ID(108), data_type: 'period', choices: [] }
];

/** A condition as the API answers with it. */
function cond(
	field: ApiCondition['field'],
	op: ApiCondition['op'],
	value: ApiCondition['value'] = null,
	extra: Partial<ApiCondition> = {}
): ApiCondition {
	return { field, op, value, field_id: null, case_sensitive: false, ...extra };
}

const fieldCondition = (n: number, op: ApiCondition['op'], value: ApiCondition['value'] = null) =>
	cond('field', op, value, { field_id: ID(n) });

const EVERY_CONDITION: ApiCondition[] = [
	cond('contact', 'is', ID(1)),
	cond('contact', 'in', [ID(2), ID(1)]),
	cond('contact', 'present'),
	cond('document_type', 'missing'),
	cond('document_type', 'in', [ID(3)]),
	cond('tags', 'contains', ID(4)),
	cond('tags', 'in', [ID(5), ID(4)]),
	cond('tags', 'present'),
	cond('tags', 'missing'),
	cond('channel', 'is', 'web'),
	cond('channel', 'in', ['api', 'migration']),
	cond('text', 'contains', ' Rechnung '),
	cond('text', 'matches', 'Rechnung\\s+Nr', { case_sensitive: true }),
	cond('document_date', 'is', '2026-01-31'),
	cond('document_date', 'gt', '2025-12-31'),
	cond('document_date', 'lt', '2027-01-01'),
	cond('document_date', 'present'),
	fieldCondition(101, 'is', 'ACME'),
	fieldCondition(101, 'in', ['ACME', 'Globex']),
	fieldCondition(101, 'contains', 'acme'),
	fieldCondition(101, 'matches', '^A'),
	fieldCondition(102, 'is', 'https://example.org'),
	fieldCondition(103, 'gt', '12.5'),
	fieldCondition(103, 'is', '3'),
	fieldCondition(104, 'lt', { amount: '100', currency: 'EUR' }),
	fieldCondition(105, 'gt', '2026-01-01'),
	fieldCondition(106, 'is', true),
	fieldCondition(106, 'is', false),
	fieldCondition(106, 'missing'),
	fieldCondition(107, 'is', 'monthly'),
	fieldCondition(107, 'in', ['monthly', 'yearly'])
];

const EVERY_ACTION: ApiDefinition['actions'] = [
	{ type: 'set_space', space_id: ID(10) },
	{ type: 'set_contact', contact_id: ID(1) },
	{ type: 'set_document_type', document_type_id: ID(3) },
	{
		type: 'set_title',
		template: "{{ contact }} {{ document_type }} {{ document_date | date: '%Y' }} {{ filename }}"
	},
	{ type: 'add_tags', tag_ids: [ID(4), ID(5)] },
	{ type: 'remove_tags', tag_ids: [ID(6)] },
	{ type: 'set_field', field_id: ID(104), value: { amount: '12.50', currency: 'EUR' } },
	{ type: 'set_field', field_id: ID(106), value: false },
	{ type: 'force_review', reason: 'check the contract term' }
];

function definition(conditions: ApiGroup, actions = EVERY_ACTION): ApiDefinition {
	return { name: 'Everything', priority: 250, triggers: ['change', 'ingest'], conditions, actions };
}

/** Groups `depth` deep, the innermost holding `items`. */
function nested(depth: number, items: ApiCondition[]): ApiGroup {
	let group: ApiGroup = { any: items, not: true };
	for (let level = 1; level < depth; level++) {
		group =
			level % 2
				? { all: [cond('text', 'contains', `x${level}`), group], not: false }
				: { any: [group], not: level === 2 };
	}
	return group;
}

describe('the rule model', () => {
	it('gives every condition and action back unchanged', () => {
		const api = definition({ all: EVERY_CONDITION, not: false });
		expect(toApi(fromApi(api))).toEqual(api);
	});

	it('keeps repeated values of a list', () => {
		const api = definition({
			all: [cond('channel', 'in', ['web', 'web']), cond('tags', 'in', [ID(4), ID(4)])],
			not: false
		});
		expect(toApi(fromApi(api))).toEqual(api);
	});

	it('keeps nesting, negation and limits unchanged', () => {
		const deep = definition(nested(LIMITS.depth, [cond('channel', 'is', 'api')]));
		expect(toApi(fromApi(deep))).toEqual(deep);
		const many = definition({
			any: Array.from({ length: LIMITS.conditions }, (_, n) => cond('text', 'contains', `t${n}`)),
			not: false
		});
		const model = fromApi(many);
		expect(conditionsOf(model.conditions)).toHaveLength(LIMITS.conditions);
		expect(toApi(model)).toEqual(many);
		expect(validate(model, FIELDS)).toEqual({});
	});

	it('round-trips references to deleted things as they are', () => {
		const api = definition({ all: [cond('contact', 'is', ID(999))], not: false }, [
			{ type: 'add_tags', tag_ids: [ID(998)] }
		]);
		expect(toApi(fromApi(api))).toEqual(api);
	});

	it('sorts triggers and tags as the API does, and drops the keys', () => {
		const model = newModel();
		model.name = 'Tax';
		model.triggers = ['ingest', 'change'];
		model.actions.push({ ...newAction('add_tags'), tag_ids: [ID(5), ID(4)] } as never);
		const out = toApi(model);
		expect(out.triggers).toEqual(['change', 'ingest']);
		expect(out.actions).toEqual([{ type: 'add_tags', tag_ids: [ID(4), ID(5)] }]);
	});

	it('mirrors the operator tables of the core', () => {
		expect(CONDITION_FIELD_OPERATORS).toEqual({
			contact: ['is', 'in', 'present', 'missing'],
			contact_group: ['contains', 'in', 'present', 'missing'],
			document_type: ['is', 'in', 'present', 'missing'],
			document_type_group: ['contains', 'in', 'present', 'missing'],
			topic: ['is', 'in', 'present', 'missing'],
			tags: ['contains', 'in', 'present', 'missing'],
			channel: ['is', 'in'],
			text: ['contains', 'matches'],
			document_date: ['is', 'gt', 'lt', 'present', 'missing'],
			step: ['is', 'in', 'contains', 'gt', 'lt', 'present', 'missing'],
			fact: ['present', 'missing', 'is', 'in', 'matches']
		});
		expect(FIELD_TYPE_OPERATORS.boolean).toEqual(['is', 'present', 'missing']);
		expect(FIELD_TYPE_OPERATORS.choice).toEqual(['is', 'in', 'present', 'missing']);
		expect(FIELD_TYPE_OPERATORS.amount).toEqual(['is', 'gt', 'lt', 'present', 'missing']);
		expect(FIELD_TYPE_OPERATORS.link).toEqual(FIELD_TYPE_OPERATORS.text);
		expect(FIELD_TYPE_OPERATORS.period).toEqual([
			'is',
			'overlaps',
			'gt',
			'lt',
			'present',
			'missing'
		]);
	});
});

describe('a condition on facts', () => {
	it('goes to the API with its kind and role and comes back', () => {
		const model = newModel();
		const condition = model.conditions.items[0] as ConditionNode;
		changeConditionField(condition, 'fact', []);
		expect([condition.factKind, condition.op]).toEqual(['invoice_number', 'present']);
		condition.factRole = 'refers';
		const api = toApi(model);
		expect(api.conditions).toMatchObject({
			all: [{ field: 'fact', op: 'present', fact_kind: 'invoice_number', fact_role: 'refers' }]
		});
		const again = fromApi(api).conditions.items[0] as ConditionNode;
		expect([again.factKind, again.factRole]).toEqual(['invoice_number', 'refers']);
	});
});

describe('editing conditions', () => {
	it('resets operator and value for another field or field', () => {
		const condition = newCondition('contact');
		condition.value = ID(1);
		changeConditionField(condition, 'text', FIELDS);
		expect([condition.op, condition.value]).toEqual(['contains', '']);
		changeConditionField(condition, 'field', FIELDS);
		changeField(condition, ID(106), FIELDS);
		expect([condition.op, condition.value]).toEqual(['is', true]);
		changeField(condition, ID(104), FIELDS);
		expect(condition.value).toEqual({ amount: '', currency: 'EUR' });
		// A period compares with a period, or with a date for starts after and ends before.
		changeField(condition, ID(108), FIELDS);
		expect([condition.op, condition.value]).toEqual(['is', { start: '', end: '' }]);
		changeOperator(condition, 'gt', FIELDS);
		expect(condition.value).toBe('');
	});

	it('keeps a value between one and a list', () => {
		const condition: ConditionNode = { ...newCondition('contact'), value: ID(1) };
		changeOperator(condition, 'in', FIELDS);
		expect(condition.value).toEqual([ID(1)]);
		changeOperator(condition, 'is', FIELDS);
		expect(condition.value).toBe(ID(1));
		changeOperator(condition, 'present', FIELDS);
		expect(condition.value).toBeNull();
		const text: ConditionNode = { ...newCondition('text'), value: 'x', caseSensitive: true };
		changeOperator(text, 'matches', FIELDS);
		changeOperator(text, 'contains', FIELDS);
		expect([text.value, text.caseSensitive]).toEqual(['x', false]);
	});

	it('moves items and stops groups at the depth limit', () => {
		const items = [1, 2, 3];
		move(items, 0, -1);
		move(items, 2, 1);
		move(items, 1, 1);
		expect(items).toEqual([1, 3, 2]);
		const model = fromApi(definition(nested(LIMITS.depth, [cond('channel', 'is', 'api')])));
		let innermost: GroupNode = model.conditions;
		while (innermost.items.some((item) => item.kind === 'group')) {
			innermost = innermost.items.find((item) => item.kind === 'group') as GroupNode;
		}
		expect(canAddGroup(model, innermost)).toBe(false);
		expect(canAddGroup(model, model.conditions)).toBe(true);
	});
});

describe('checking a rule', () => {
	function problems(model: RuleModel) {
		return Object.fromEntries(
			Object.entries(validate(model, FIELDS)).map(([key, problem]) => [key, problem.code])
		);
	}

	it('names every missing part by its key', () => {
		const model = newModel();
		model.priority = 1001;
		model.triggers = [];
		const empty = newGroup('any');
		model.conditions.items.push(empty);
		const condition = model.conditions.items[0] as ConditionNode;
		expect(problems(model)).toEqual({
			name: 'name',
			priority: 'priority',
			triggers: 'triggers',
			[condition.key]: 'choose',
			[empty.key]: 'group_empty',
			actions: 'actions_none'
		});
	});

	it('checks values by field and field type', () => {
		const model = newModel();
		model.name = 'x';
		model.actions = [{ ...newAction('force_review'), reason: 'why' } as never];
		const cases: [Partial<ConditionNode>, string | undefined][] = [
			[{ field: 'text', op: 'contains', value: '  ' }, 'value'],
			[{ field: 'text', op: 'matches', value: 'x'.repeat(201) }, 'text_long'],
			[{ field: 'document_date', op: 'gt', value: '31.12.2026' }, 'date'],
			[{ field: 'channel', op: 'in', value: [] }, 'list'],
			[{ field: 'field', op: 'is', value: 'x', fieldId: null }, 'field'],
			[{ field: 'field', op: 'gt', value: 'seven', fieldId: ID(103) }, 'number'],
			[
				{
					field: 'field',
					op: 'is',
					value: { amount: '1', currency: 'eur' },
					fieldId: ID(104)
				},
				'amount'
			],
			[{ field: 'field', op: 'contains', value: 'x', fieldId: ID(103) }, 'operator'],
			[{ field: 'field', op: 'in', value: ['monthly'], fieldId: ID(107) }, undefined],
			[{ field: 'field', op: 'missing', value: null, fieldId: ID(999) }, undefined],
			// What the API accepts as well: other date and number spellings, long text values.
			[{ field: 'document_date', op: 'gt', value: '20240115' }, undefined],
			[{ field: 'document_date', op: 'gt', value: '2024-W03-1' }, undefined],
			[{ field: 'field', op: 'gt', value: '1e3', fieldId: ID(103) }, undefined],
			[{ field: 'field', op: 'gt', value: '1_000.5', fieldId: ID(103) }, undefined],
			[{ field: 'field', op: 'gt', value: 'inf', fieldId: ID(103) }, 'number'],
			[{ field: 'field', op: 'is', value: 'x'.repeat(600), fieldId: ID(101) }, undefined],
			[
				{
					field: 'field',
					op: 'overlaps',
					value: { start: '2026-09-30', end: '2026-09-01' },
					fieldId: ID(108)
				},
				'period'
			],
			[
				{
					field: 'field',
					op: 'is',
					value: { start: '2026-09-01', end: '2026-09-30' },
					fieldId: ID(108)
				},
				undefined
			],
			[{ field: 'field', op: 'gt', value: { start: '', end: '' }, fieldId: ID(108) }, 'date'],
			[{ field: 'field', op: 'lt', value: '2026-10-01', fieldId: ID(108) }, undefined]
		];
		for (const [change, code] of cases) {
			const condition = { ...newCondition(), ...change } as ConditionNode;
			model.conditions.items = [condition];
			expect(problems(model)[condition.key], JSON.stringify(change)).toBe(code);
		}
	});

	it('checks actions and fields set twice; a global rule may do everything', () => {
		const model = newModel();
		model.name = 'x';
		model.conditions.items = [{ ...newCondition('channel'), value: 'web' }];
		const space = {
			...newAction('set_space'),
			space_id: ID(10)
		} as never as RuleModel['actions'][number];
		const title = {
			...newAction('set_title'),
			template: ''
		} as never as RuleModel['actions'][number];
		const first = {
			...newAction('set_contact'),
			contact_id: ID(1)
		} as never as RuleModel['actions'][number];
		const second = {
			...newAction('set_contact'),
			contact_id: ID(2)
		} as never as RuleModel['actions'][number];
		const tags = newAction('add_tags');
		model.actions = [space, title, first, second, tags];
		expect(problems(model)).toEqual({
			[title.key]: 'value',
			[second.key]: 'twice',
			[tags.key]: 'list'
		});
	});

	it('checks a field value as a template or as a fixed value', () => {
		const model = newModel();
		model.name = 'x';
		model.conditions.items = [{ ...newCondition('channel'), value: 'web' }];
		const cases: [string, unknown, boolean | undefined, string | undefined][] = [
			// A fixed value by its type; text another type cannot hold as JSON is a template.
			[ID(104), { amount: '1', currency: 'eur' }, undefined, 'amount'],
			[ID(104), '{{ steps.erp.total }} EUR', undefined, undefined],
			[ID(104), '  ', undefined, 'value'],
			[ID(103), '12,50', undefined, undefined],
			[ID(103), '12,50', false, 'number'],
			[ID(105), '15.03.2026', undefined, undefined],
			[ID(105), '15.03.2026', false, 'date'],
			[ID(107), '{{ steps.erp.state }}', undefined, undefined],
			[ID(107), 'x'.repeat(501), true, 'text_long'],
			[ID(106), 'ja', true, undefined]
		];
		for (const [field_id, value, templated, code] of cases) {
			const action = {
				...newAction('set_field'),
				field_id,
				value,
				...(templated === undefined ? {} : { templated })
			} as never as RuleModel['actions'][number];
			model.actions = [action];
			expect(problems(model)[action.key], JSON.stringify([field_id, value])).toBe(code);
		}
	});

	it('takes a topic like a contact: one value', () => {
		const model = newModel();
		model.name = 'x';
		model.conditions.items = [{ ...newCondition('topic'), value: ID(5) }];
		expect(model.conditions.items[0]).toMatchObject({ op: 'is' });
		const topic = newAction('set_topic');
		model.actions = [topic];
		expect(problems(model)).toEqual({ [topic.key]: 'choose' });
		expect(referencedIds({ ...topic, topic_id: ID(6) } as never)).toEqual([ID(6)]);
		expect(referencedIds(model.conditions.items[0] as never)).toEqual([ID(5)]);
	});
});

describe('errors of saving', () => {
	const model = fromApi(
		definition(
			{
				all: [
					cond('contact', 'is', ID(1)),
					{ any: [cond('tags', 'in', [ID(4)]), fieldCondition(103, 'gt', '1')], not: false }
				],
				not: false
			},
			[
				{ type: 'add_tags', tag_ids: [ID(4)] },
				{ type: 'set_space', space_id: ID(10) }
			]
		)
	);
	const group = model.conditions.items[1] as GroupNode;

	it('finds the block of a place', () => {
		expect(keyAt('conditions.all[1].any[1]', model)).toBe(group.items[1].key);
		expect(
			keyAt('conditions.AllGroup-Input.all.1.AnyGroup-Input.any.0.ConditionSchema.value', model)
		).toBe(group.items[0].key);
		expect(keyAt('conditions', model)).toBe(model.conditions.key);
		expect(keyAt('actions[1]', model)).toBe(model.actions[1].key);
		expect(keyAt('actions.0.add_tags.tag_ids', model)).toBe(model.actions[0].key);
		expect(keyAt('conditions.all[7]', model)).toBeNull();
		expect(keyAt('name', model)).toBe('name');
	});

	it('keeps only the kinds of the blocks from request validation', () => {
		const detail = [
			'conditions.AllGroup.all.1.ConditionSchema.field: Field required',
			'conditions.AllGroup.all.1.AllGroup.all: Field required',
			"conditions.AllGroup.all.1.AnyGroup.any.0.ConditionSchema.op: Input should be 'is'",
			'conditions.AllGroup.all.1.AnyGroup.any.0.AllGroup.all: Field required',
			'conditions.AnyGroup.any: Field required'
		].join('; ');
		expect(saveErrors(failed(422, detail), model)).toEqual({
			byKey: { [group.items[0].key]: "Input should be 'is'" },
			general: null
		});
		// A message with "; " in it stays whole.
		const unknown = failed(422, 'actions[0]: unknown value x; templates know contact; and more');
		expect(saveErrors(unknown, model).byKey).toEqual({
			[model.actions[0].key]: 'unknown value x; templates know contact; and more'
		});
	});

	it('puts messages next to their block', () => {
		const invalid = failed(422, "conditions.all[1].any[1]: operator 'contains' does not apply");
		expect(saveErrors(invalid, model)).toEqual({
			byKey: { [group.items[1].key]: "operator 'contains' does not apply" },
			general: null
		});
		const missing = failed(404, `tag ${ID(4)} not found`);
		expect(Object.keys(saveErrors(missing, model).byKey)).toEqual([
			group.items[0].key,
			model.actions[0].key
		]);
		const forbidden = failed(403, "no write access to space 'Office'", ID(8));
		expect(Object.keys(saveErrors(forbidden, model).byKey)).toEqual([model.actions[1].key]);
		const elsewhere = failed(403, 'only admins change global rules');
		expect(saveErrors(elsewhere, model).byKey).toEqual({});
		const typed = fromApi(
			definition({ all: [cond('channel', 'is', 'web')], not: false }, [
				{ type: 'set_document_type', document_type_id: ID(9) }
			])
		);
		const type = failed(404, `document type ${ID(9)} not found`);
		expect(Object.keys(saveErrors(type, typed).byKey)).toEqual([typed.actions[0].key]);
		const other = failed(409, 'changed meanwhile');
		expect(saveErrors(other, model)).toEqual({ byKey: {}, general: 'changed meanwhile' });
	});
});

describe('steps of a rule', () => {
	const HOOK = ID(900);
	const stepsDefinition: ApiDefinition = {
		name: 'Invoices',
		priority: 100,
		triggers: ['ingest'],
		conditions: {
			all: [{ field: 'channel', op: 'is', value: 'api', field_id: null, case_sensitive: false }],
			not: false
		},
		actions: [
			{
				type: 'ask_webhook',
				name: 'flow',
				webhook_id: HOOK,
				timeout_seconds: 120,
				missing: 'yellow'
			},
			{
				type: 'condition',
				conditions: {
					any: [
						{
							field: 'step',
							op: 'is',
							value: true,
							path: 'flow.paid',
							field_id: null,
							case_sensitive: false
						},
						{
							field: 'step',
							op: 'gt',
							value: 12.5,
							path: 'flow.amount',
							field_id: null,
							case_sensitive: false
						}
					],
					not: false
				}
			},
			{ type: 'add_tags', tag_ids: [ID(1)] }
		]
	};

	it('gives asking and condition steps back unchanged', () => {
		const model = fromApi(stepsDefinition);
		const condition = model.actions[1];
		expect(condition.type === 'condition' && condition.conditions.kind).toBe('group');
		expect(toApi(model)).toEqual(stepsDefinition);
	});

	it('runs a rule that asks on arrival only', () => {
		const model = fromApi(stepsDefinition);
		expect(validate(model, FIELDS)).toEqual({});
		model.triggers = ['change', 'ingest'];
		expect(validate(model, FIELDS).triggers).toEqual({ code: 'triggers_ask' });
	});

	it('checks names, times and what a condition step looks at', () => {
		const model = fromApi(stepsDefinition);
		const [ask, condition] = model.actions;
		if (ask.type !== 'ask_webhook' || condition.type !== 'condition') throw new Error('steps');
		ask.timeout_seconds = 10;
		expect(validate(model, FIELDS)[ask.key]).toMatchObject({ code: 'timeout' });
		ask.timeout_seconds = 60;
		ask.name = 'Flow';
		const problems = validate(model, FIELDS);
		expect(problems[ask.key]).toEqual({ code: 'step_name' });
		const [first, second] = conditionsOf(condition.conditions);
		expect(problems[first.key]).toEqual({ code: 'step_unknown' });
		second.path = 'flow..amount';
		expect(validate(model, FIELDS)[second.key]).toEqual({ code: 'path' });
	});

	it('wants an action besides conditions, and a step name once', () => {
		const model = newModel();
		model.name = 'x';
		model.triggers = ['ingest'];
		model.actions = [newAction('condition')];
		expect(validate(model, FIELDS).actions).toEqual({ code: 'actions_none' });
		const one = newAction('ask_webhook');
		const two = newAction('ask_webhook');
		for (const step of [one, two]) {
			if (step.type === 'ask_webhook') Object.assign(step, { name: 'flow', webhook_id: HOOK });
		}
		model.actions = [one, two];
		expect(validate(model, FIELDS)[two.key]).toEqual({ code: 'twice' });
	});

	it('names the webhook a step asks and the ids its conditions name', () => {
		const model = fromApi(stepsDefinition);
		expect(referencedIds(model.actions[0])).toEqual([HOOK]);
		const condition = newAction('condition');
		if (condition.type === 'condition') {
			condition.conditions.items = [{ ...newCondition('contact'), value: ID(5) }];
		}
		expect(referencedIds(condition)).toEqual([ID(5)]);
	});
});

describe('a field value as a template', () => {
	const field = (id: number) => FIELDS.find((entry) => entry.id === ID(id))!;

	it('tells a template from a fixed value by the field type', () => {
		expect(isTemplated(field(101), 'plain')).toBe(true);
		expect(isTemplated(field(103), '12.50')).toBe(false);
		expect(isTemplated(field(103), '12,50 €')).toBe(true);
		expect(isTemplated(field(104), { amount: '1', currency: 'EUR' })).toBe(false);
		expect(isTemplated(field(104), '12.50 EUR')).toBe(true);
		expect(isTemplated(field(105), '2026-03-15')).toBe(false);
		expect(isTemplated(field(106), false)).toBe(false);
		expect(isTemplated(field(107), 'yearly')).toBe(false);
		expect(isTemplated(field(107), '{% if x %}yearly{% endif %}')).toBe(true);
		expect(isTemplated(field(102), 'https://example.org/{{ filename }}')).toBe(true);
	});

	it('turns a fixed value into the text of a template and back', () => {
		expect(asTemplate({ amount: '12.50', currency: 'EUR' })).toBe('12.50 EUR');
		expect(asTemplate({ amount: '', currency: 'EUR' })).toBe('');
		expect(asTemplate({ start: '2026-07-01', end: '2026-09-30' })).toBe('2026-Q3');
		expect(asTemplate(false)).toBe('false');
		expect(asFixed(field(104), '12.50 EUR')).toEqual({ amount: '12.50', currency: 'EUR' });
		expect(asFixed(field(104), '{{ x }}')).toEqual({ amount: '', currency: 'EUR' });
		expect(asFixed(field(108), '2026-Q3')).toEqual({ start: '2026-07-01', end: '2026-09-30' });
		expect(asFixed(field(106), 'false')).toBe(false);
		expect(asFixed(field(106), '{{ x }}')).toBe(true);
		expect(asFixed(field(103), '7')).toBe('7');
		expect(asFixed(field(103), '7 Stück')).toBe('');
	});

	it('sends the value, not how the builder edits it', () => {
		const model = newModel();
		model.name = 'x';
		model.actions = [
			{ ...newAction('set_field'), field_id: ID(103), value: '{{ x }}', templated: true } as never
		];
		expect(toApi(model).actions).toEqual([
			{ type: 'set_field', field_id: ID(103), value: '{{ x }}' }
		]);
	});
});
