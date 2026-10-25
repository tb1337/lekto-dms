/**
 * A rule as the builder edits it: the API's definition with a key on every group, condition
 * and action, so that errors and focus find their block. Values keep the API's JSON form, so
 * that `toApi(fromApi(definition))` gives the definition back unchanged.
 *
 * The tables and limits mirror `lekto.core.domain.rules`; the API checks everything again.
 */
import type { components } from '#lib/api/schema.ts';
import { isMoney, isPeriod } from '#lib/fields.ts';
import { readPeriod, writePeriod } from '#lib/periods.ts';

type Schemas = components['schemas'];

export type ConditionField = Schemas['ConditionSchema']['field'];
export type Operator = Schemas['Operator'];
export type Trigger = Schemas['Trigger'];
export type Channel = Schemas['Channel'];
export type Scope = Schemas['RuleScope'];
export type FieldType = Schemas['FieldType'];
export type Money = Schemas['MoneyValue'];
export type Period = Schemas['PeriodValue'];
export type Value =
	string | boolean | number | Money | Period | string[] | (string | number | boolean)[] | null;
export type ApiCondition = Schemas['ConditionSchema'];
export type ApiGroup = Schemas['AllGroup-Output'] | Schemas['AnyGroup-Output'];
export type ApiAction = Schemas['RuleOut']['actions'][number];
export type ActionType = ApiAction['type'];
export type Missing = Schemas['Missing'];
export type ApiDefinition = Pick<
	Schemas['RuleOut'],
	'name' | 'priority' | 'triggers' | 'conditions' | 'actions'
>;

export interface ConditionNode {
	kind: 'condition';
	key: string;
	field: ConditionField;
	op: Operator;
	value: Value;
	fieldId: string | null;
	caseSensitive: boolean;
	/** A condition on what a step brought: `<step>.<key>…`; null for other fields. */
	path: string | null;
}

export interface GroupNode {
	kind: 'group';
	key: string;
	mode: 'all' | 'any';
	negate: boolean;
	items: RuleNode[];
}

export type RuleNode = ConditionNode | GroupNode;
/** A step that checks: its conditions as the builder edits them. */
export interface ConditionStepNode {
	key: string;
	type: 'condition';
	conditions: GroupNode;
}
export type ActionNode =
	| (Exclude<ApiAction, { type: 'condition' | 'set_field' }> & { key: string })
	| SetFieldNode
	| ConditionStepNode;
/** Setting a field: `templated` says whether the value is edited as a template or as a fixed
 * value (the builder's own, not sent; unset: `isTemplated` decides from the value). */
export type SetFieldNode = Extract<ApiAction, { type: 'set_field' }> & {
	key: string;
	templated?: boolean;
};

export interface RuleModel {
	name: string;
	priority: number;
	triggers: Trigger[];
	conditions: GroupNode;
	actions: ActionNode[];
}

/** What the builder needs to know about a field. */
export interface FieldInfo {
	id: string;
	data_type: FieldType;
	choices: readonly string[];
}

export const LIMITS = {
	depth: 5,
	conditions: 50,
	actions: 20,
	list: 100,
	text: 500,
	pattern: 200,
	name: 200,
	priorityMin: 0,
	priorityMax: 1000
} as const;

export const DEFAULT_PRIORITY = 100;
export const TRIGGERS: readonly Trigger[] = ['ingest', 'change'];
export const CHANNELS: readonly Channel[] = ['web', 'api', 'migration'];
/** The fields of a rule's head; a condition step has `step` too. */
export const CONDITION_FIELDS: readonly ConditionField[] = [
	'contact',
	'contact_group',
	'document_type',
	'document_type_group',
	'topic',
	'tags',
	'channel',
	'text',
	'document_date',
	'field'
];
export const STEP_CONDITION_FIELDS: readonly ConditionField[] = ['step', ...CONDITION_FIELDS];

const ALL_OPERATORS: readonly Operator[] = [
	'is',
	'in',
	'contains',
	'matches',
	'gt',
	'lt',
	'present',
	'missing'
];
const REFERENCE: readonly Operator[] = ['is', 'in', 'present', 'missing'];
const ORDERED: readonly Operator[] = ['is', 'gt', 'lt', 'present', 'missing'];
const TEXTUAL: readonly Operator[] = ['is', 'in', 'contains', 'matches', 'present', 'missing'];
const TAGS: readonly Operator[] = ['contains', 'in', 'present', 'missing'];

/** The condition fields on tags, and the scope of the tags each names. */
export const TAG_FIELDS = {
	tags: 'document',
	contact_group: 'contact',
	document_type_group: 'document_type'
} as const satisfies Partial<Record<ConditionField, Schemas['TagScope']>>;

export function isTagField(field: ConditionField): field is keyof typeof TAG_FIELDS {
	return field in TAG_FIELDS;
}

export const CONDITION_FIELD_OPERATORS: Record<
	Exclude<ConditionField, 'field'>,
	readonly Operator[]
> = {
	contact: REFERENCE,
	contact_group: TAGS,
	document_type: REFERENCE,
	document_type_group: TAGS,
	topic: REFERENCE,
	tags: TAGS,
	channel: ['is', 'in'],
	text: ['contains', 'matches'],
	document_date: ORDERED,
	step: ['is', 'in', 'contains', 'gt', 'lt', 'present', 'missing']
};

export const FIELD_TYPE_OPERATORS: Record<FieldType, readonly Operator[]> = {
	text: TEXTUAL,
	link: TEXTUAL,
	number: ORDERED,
	amount: ORDERED,
	date: ORDERED,
	boolean: ['is', 'present', 'missing'],
	choice: REFERENCE,
	period: ['is', 'overlaps', 'gt', 'lt', 'present', 'missing']
};

export const ACTION_TYPES: readonly ActionType[] = [
	'set_space',
	'set_contact',
	'set_document_type',
	'set_topic',
	'set_title',
	'add_tags',
	'remove_tags',
	'set_field',
	'force_review',
	'send_webhook',
	'ask_webhook',
	'condition'
];

/** A step's name, as the API takes it (`STEP_NAME`). */
export const STEP_NAME = /^[a-z][a-z0-9_]{0,49}$/;
/** What a step condition looks at: a step's name, then keys of its answer. */
export const STEP_PATH = /^[a-z][a-z0-9_]{0,49}(\.[A-Za-z0-9_-]{1,100})*$/;
export const MISSING: readonly Missing[] = ['red', 'yellow', 'continue'];
export const TIMEOUT = { min: 30, max: 86_400, default: 300 } as const;

let counter = 0;
const nextKey = (): string => `n${++counter}`;

// --- from and to the API ------------------------------------------------------------------

export function fromApi(definition: ApiDefinition): RuleModel {
	return {
		name: definition.name,
		priority: definition.priority,
		triggers: [...definition.triggers],
		conditions: groupFromApi(definition.conditions),
		actions: definition.actions.map(actionFromApi)
	};
}

function actionFromApi(action: ApiAction): ActionNode {
	if (action.type === 'condition') {
		return { key: nextKey(), type: 'condition', conditions: groupFromApi(action.conditions) };
	}
	return { ...clone(action), key: nextKey() };
}

function groupFromApi(group: ApiGroup): GroupNode {
	const mode = 'all' in group ? 'all' : 'any';
	const items = 'all' in group ? group.all : group.any;
	return {
		kind: 'group',
		key: nextKey(),
		mode,
		negate: group.not ?? false,
		items: items.map((item) => ('field' in item ? conditionFromApi(item) : groupFromApi(item)))
	};
}

function conditionFromApi(condition: ApiCondition): ConditionNode {
	return {
		kind: 'condition',
		key: nextKey(),
		field: condition.field,
		op: condition.op,
		value: clone(condition.value ?? null),
		fieldId: condition.field_id ?? null,
		caseSensitive: condition.case_sensitive ?? false,
		path: condition.path ?? null
	};
}

/** The definition in the form the API answers with (and accepts). */
export function toApi(model: RuleModel): ApiDefinition {
	return {
		name: model.name,
		priority: model.priority,
		triggers: [...model.triggers].sort(),
		conditions: groupToApi(model.conditions),
		actions: model.actions.map(actionToApi)
	};
}

function groupToApi(group: GroupNode): ApiGroup {
	const items = group.items.map((item) =>
		item.kind === 'group' ? groupToApi(item) : conditionToApi(item)
	);
	return group.mode === 'all'
		? { all: items, not: group.negate }
		: { any: items, not: group.negate };
}

function conditionToApi(condition: ConditionNode): ApiCondition {
	return {
		field: condition.field,
		op: condition.op,
		value: clone(condition.value),
		field_id: condition.fieldId,
		case_sensitive: condition.caseSensitive,
		...(condition.path === null ? {} : { path: condition.path })
	};
}

function actionToApi(node: ActionNode): ApiAction {
	if (node.type === 'condition')
		return { type: 'condition', conditions: groupToApi(node.conditions) };
	const action = clone(node) as Partial<ActionNode> & { templated?: boolean };
	delete action.key;
	delete action.templated;
	const plain = action as ApiAction;
	if (plain.type === 'add_tags' || plain.type === 'remove_tags') {
		return { ...plain, tag_ids: [...plain.tag_ids].sort() };
	}
	return plain;
}

function clone<T>(value: T): T {
	return value === null || typeof value !== 'object'
		? value
		: (JSON.parse(JSON.stringify(value)) as T);
}

// --- building -----------------------------------------------------------------------------

export function newModel(): RuleModel {
	return {
		name: '',
		priority: DEFAULT_PRIORITY,
		triggers: [...TRIGGERS],
		conditions: newGroup('all', [newCondition()]),
		actions: []
	};
}

export function newGroup(mode: 'all' | 'any' = 'all', items: RuleNode[] = []): GroupNode {
	return { kind: 'group', key: nextKey(), mode, negate: false, items };
}

export function newCondition(field: ConditionField = 'contact'): ConditionNode {
	const op = (field === 'field' ? ALL_OPERATORS : CONDITION_FIELD_OPERATORS[field])[0];
	return {
		kind: 'condition',
		key: nextKey(),
		field,
		op,
		value: defaultValue(field, op, null),
		fieldId: null,
		caseSensitive: false,
		path: field === 'step' ? '' : null
	};
}

export function newAction(type: ActionType): ActionNode {
	const key = nextKey();
	switch (type) {
		case 'set_space':
			return { key, type, space_id: '' };
		case 'set_contact':
			return { key, type, contact_id: '' };
		case 'set_document_type':
			return { key, type, document_type_id: '' };
		case 'set_topic':
			return { key, type, topic_id: '' };
		case 'set_title':
			return { key, type, template: '' };
		case 'add_tags':
		case 'remove_tags':
			return { key, type, tag_ids: [] };
		case 'set_field':
			return { key, type, field_id: '', value: '' };
		case 'force_review':
			return { key, type, reason: '' };
		case 'send_webhook':
			return { key, type, webhook_id: '' };
		case 'ask_webhook':
			return {
				key,
				type,
				name: '',
				webhook_id: '',
				timeout_seconds: TIMEOUT.default,
				missing: 'red'
			};
		case 'condition':
			return { key, type, conditions: newGroup('all', [newCondition('step')]) };
	}
}

/** Operators that take no value. */
export function takesNoValue(op: Operator): boolean {
	return op === 'present' || op === 'missing';
}

/** The operators for a condition; for a field by its data type. An unknown field keeps
 * the operator it has. */
export function operatorsFor(
	condition: Pick<ConditionNode, 'field' | 'op' | 'fieldId'>,
	fields: readonly FieldInfo[]
): readonly Operator[] {
	if (condition.field !== 'field') return CONDITION_FIELD_OPERATORS[condition.field];
	if (condition.fieldId === null) return ALL_OPERATORS;
	const field = fields.find((entry) => entry.id === condition.fieldId);
	return field ? FIELD_TYPE_OPERATORS[field.data_type] : [condition.op];
}

/** The empty value for a field and operator. */
export function defaultValue(
	conditionField: ConditionField,
	op: Operator,
	field: FieldInfo | null
): Value {
	if (takesNoValue(op)) return null;
	if (op === 'in') return [];
	if (conditionField === 'field' && field && op !== 'contains' && op !== 'matches') {
		if (field.data_type === 'boolean') return true;
		if (field.data_type === 'amount') return { amount: '', currency: 'EUR' };
		// A period's `gt` and `lt` compare with a date: it starts after, it ends before.
		if (field.data_type === 'period' && op !== 'gt' && op !== 'lt') return { start: '', end: '' };
	}
	return '';
}

/** A new condition field: the first operator for it and an empty value. */
export function changeConditionField(
	condition: ConditionNode,
	field: ConditionField,
	fields: readonly FieldInfo[]
): void {
	condition.field = field;
	condition.fieldId = null;
	condition.caseSensitive = false;
	condition.path = field === 'step' ? '' : null;
	condition.op = operatorsFor(condition, fields)[0];
	condition.value = defaultValue(field, condition.op, null);
}

/** Another field: its first fitting operator unless the current one fits, empty value. */
export function changeField(
	condition: ConditionNode,
	fieldId: string,
	fields: readonly FieldInfo[]
): void {
	condition.fieldId = fieldId;
	const operators = operatorsFor(condition, fields);
	if (!operators.includes(condition.op)) condition.op = operators[0];
	if (condition.op !== 'matches') condition.caseSensitive = false;
	const field = fields.find((entry) => entry.id === fieldId) ?? null;
	condition.value = defaultValue('field', condition.op, field);
}

/** Another operator; a value that still fits stays (one value into a list and back). */
export function changeOperator(
	condition: ConditionNode,
	op: Operator,
	fields: readonly FieldInfo[]
): void {
	const before = condition.value;
	const field = fields.find((entry) => entry.id === condition.fieldId) ?? null;
	condition.op = op;
	if (op !== 'matches') condition.caseSensitive = false;
	const empty = defaultValue(condition.field, op, field);
	if (empty === null) {
		condition.value = null;
	} else if (Array.isArray(empty)) {
		condition.value = typeof before === 'string' && before !== '' ? [before] : [];
	} else if (Array.isArray(before)) {
		condition.value = typeof empty === 'string' && before.length > 0 ? before[0] : empty;
	} else {
		condition.value =
			before !== null && typeof before === typeof empty && !isEmpty(before) ? before : empty;
	}
}

function isEmpty(value: Value): boolean {
	if (value === null || value === '') return true;
	if (Array.isArray(value)) return value.length === 0;
	if (isMoney(value)) return value.amount === '';
	if (isPeriod(value)) return value.start === '' || value.end === '';
	return false;
}

// --- the tree -----------------------------------------------------------------------------

/** All conditions, depth first. */
export function conditionsOf(group: GroupNode): ConditionNode[] {
	return group.items.flatMap((item) => (item.kind === 'group' ? conditionsOf(item) : [item]));
}

/** The conditions of the rule's head and of its condition steps. */
export function allConditions(model: RuleModel): ConditionNode[] {
	return [
		...conditionsOf(model.conditions),
		...model.actions.flatMap((action) =>
			action.type === 'condition' ? conditionsOf(action.conditions) : []
		)
	];
}

/** The names of the steps that ask before the step at `index`: what its conditions and
 * templates may look at (`steps.<name>`). */
export function asksBefore(model: RuleModel, index: number): string[] {
	return model.actions
		.slice(0, index)
		.flatMap((action) => (action.type === 'ask_webhook' && action.name ? [action.name] : []));
}

/** 1 for a group without subgroups. */
export function depthOf(group: GroupNode): number {
	return 1 + Math.max(0, ...group.items.map((item) => (item.kind === 'group' ? depthOf(item) : 0)));
}

/** The level of a group in the tree, 1 for the root; 0 if it is not in it. */
export function levelOf(root: GroupNode, key: string, level = 1): number {
	if (root.key === key) return level;
	for (const item of root.items) {
		if (item.kind !== 'group') continue;
		const found = levelOf(item, key, level + 1);
		if (found) return found;
	}
	return 0;
}

export function canAddCondition(model: RuleModel): boolean {
	return allConditions(model).length < LIMITS.conditions;
}

/** A subgroup in `group` stays within the depth limit and brings a condition with it. */
export function canAddGroup(model: RuleModel, group: GroupNode): boolean {
	const roots = [
		model.conditions,
		...model.actions.flatMap((action) => (action.type === 'condition' ? [action.conditions] : []))
	];
	const level = Math.max(...roots.map((root) => levelOf(root, group.key)));
	return canAddCondition(model) && level < LIMITS.depth;
}

/** Move the item at `index` one place up (-1) or down (+1). */
export function move<T>(items: T[], index: number, by: -1 | 1): void {
	const target = index + by;
	if (target < 0 || target >= items.length) return;
	[items[index], items[target]] = [items[target], items[index]];
}

/** The field an action sets alone; two such actions contradict each other (a webhook twice
 * would send twice). */
export function singleKey(action: ApiAction | ActionNode): string | null {
	if (action.type === 'set_field') return `field:${action.field_id}`;
	if (action.type === 'send_webhook') return `send_webhook:${action.webhook_id}`;
	if (action.type === 'ask_webhook') return `step:${action.name}`;
	if (action.type === 'add_tags' || action.type === 'remove_tags') return null;
	if (action.type === 'force_review' || action.type === 'condition') return null;
	return action.type;
}

/** The ids a condition or action refers to. */
export function referencedIds(node: ConditionNode | ActionNode): string[] {
	if ('kind' in node && node.kind === 'condition') {
		const ids: string[] = node.fieldId ? [node.fieldId] : [];
		if (
			node.field === 'contact' ||
			node.field === 'document_type' ||
			node.field === 'topic' ||
			isTagField(node.field)
		) {
			const values = Array.isArray(node.value) ? node.value : [node.value];
			ids.push(...values.filter((value): value is string => typeof value === 'string'));
		}
		return ids;
	}
	const action = node as ActionNode;
	switch (action.type) {
		case 'set_space':
			return [action.space_id];
		case 'set_contact':
			return [action.contact_id];
		case 'set_document_type':
			return [action.document_type_id];
		case 'set_topic':
			return [action.topic_id];
		case 'add_tags':
		case 'remove_tags':
			return [...action.tag_ids];
		case 'set_field':
			return [action.field_id];
		case 'send_webhook':
		case 'ask_webhook':
			return [action.webhook_id];
		case 'condition':
			return conditionsOf(action.conditions).flatMap(referencedIds);
		default:
			return [];
	}
}

// --- checking before saving ----------------------------------------------------------------

export type ProblemCode =
	| 'name'
	| 'name_long'
	| 'priority'
	| 'triggers'
	| 'value'
	| 'choose'
	| 'list'
	| 'list_long'
	| 'text_long'
	| 'date'
	| 'number'
	| 'amount'
	| 'period'
	| 'field'
	| 'operator'
	| 'group_empty'
	| 'conditions_many'
	| 'depth'
	| 'actions_none'
	| 'actions_many'
	| 'twice'
	| 'triggers_ask'
	| 'step_name'
	| 'timeout'
	| 'path'
	| 'step_unknown';

export interface Problem {
	code: ProblemCode;
	params?: Record<string, string | number>;
}

/** Problems by key: `name`, `priority`, `triggers`, `actions`, or a group's, condition's or
 * action's key. Empty if the rule may be saved. */
export function validate(model: RuleModel, fields: readonly FieldInfo[]): Record<string, Problem> {
	const problems: Record<string, Problem> = {};
	const name = model.name.trim();
	if (name === '') problems.name = { code: 'name' };
	else if (name.length > LIMITS.name)
		problems.name = { code: 'name_long', params: { max: LIMITS.name } };
	if (
		!Number.isInteger(model.priority) ||
		model.priority < LIMITS.priorityMin ||
		model.priority > LIMITS.priorityMax
	) {
		problems.priority = { code: 'priority' };
	}
	if (model.triggers.length === 0) problems.triggers = { code: 'triggers' };
	const asks = model.actions.some((action) => action.type === 'ask_webhook');
	if (asks && (model.triggers.length !== 1 || model.triggers[0] !== 'ingest')) {
		problems.triggers = { code: 'triggers_ask' };
	}
	checkGroup(model.conditions, problems, fields, []);
	if (depthOf(model.conditions) > LIMITS.depth) {
		problems[model.conditions.key] = { code: 'depth', params: { max: LIMITS.depth } };
	}
	if (allConditions(model).length > LIMITS.conditions) {
		problems[model.conditions.key] = {
			code: 'conditions_many',
			params: { max: LIMITS.conditions }
		};
	}
	if (model.actions.every((action) => action.type === 'condition')) {
		problems.actions = { code: 'actions_none' };
	}
	if (model.actions.length > LIMITS.actions) {
		problems.actions = { code: 'actions_many', params: { max: LIMITS.actions } };
	}
	const seen = new Set<string>();
	model.actions.forEach((action, index) => {
		if (action.type === 'condition') {
			checkGroup(action.conditions, problems, fields, asksBefore(model, index));
			if (depthOf(action.conditions) > LIMITS.depth) {
				problems[action.key] = { code: 'depth', params: { max: LIMITS.depth } };
			}
		}
		const problem = checkAction(action, fields);
		if (problem) problems[action.key] = problem;
		const single = singleKey(action);
		if (single !== null && seen.has(single)) problems[action.key] ??= { code: 'twice' };
		if (single !== null) seen.add(single);
	});
	return problems;
}

/** `steps`: the steps that ask before (a condition step's); the head has none. */
function checkGroup(
	group: GroupNode,
	problems: Record<string, Problem>,
	fields: readonly FieldInfo[],
	steps: readonly string[]
): void {
	if (group.items.length === 0) problems[group.key] = { code: 'group_empty' };
	for (const item of group.items) {
		if (item.kind === 'group') {
			checkGroup(item, problems, fields, steps);
		} else {
			const problem = checkCondition(item, fields, steps);
			if (problem) problems[item.key] = problem;
		}
	}
}

function checkCondition(
	condition: ConditionNode,
	fields: readonly FieldInfo[],
	steps: readonly string[] = []
): Problem | null {
	if (condition.field === 'step') {
		const path = condition.path ?? '';
		if (!STEP_PATH.test(path)) return { code: 'path' };
		if (!steps.includes(path.split('.')[0])) return { code: 'step_unknown' };
	}
	if (condition.field === 'field' && !condition.fieldId) return { code: 'field' };
	const field = fields.find((entry) => entry.id === condition.fieldId) ?? null;
	if (field && !FIELD_TYPE_OPERATORS[field.data_type].includes(condition.op)) {
		return { code: 'operator' };
	}
	if (takesNoValue(condition.op)) return null;
	const values = condition.op === 'in' ? condition.value : [condition.value];
	if (!Array.isArray(values)) return { code: 'list' };
	if (values.length === 0) return { code: 'list' };
	if (values.length > LIMITS.list) return { code: 'list_long', params: { max: LIMITS.list } };
	for (const value of values) {
		const problem = checkValue(condition, field, value);
		if (problem) return problem;
	}
	return null;
}

function checkValue(
	condition: ConditionNode,
	field: FieldInfo | null,
	value: Value
): Problem | null {
	const textual = condition.op === 'contains' || condition.op === 'matches';
	if (condition.field === 'step') return checkStepValue(condition.op, value);
	if (condition.field === 'text' || (condition.field === 'field' && textual)) {
		return checkText(value, condition.op === 'matches' ? LIMITS.pattern : LIMITS.text);
	}
	switch (condition.field) {
		case 'contact':
		case 'document_type':
		case 'topic':
		case 'tags':
		case 'contact_group':
		case 'document_type_group':
		case 'channel':
			return typeof value === 'string' && value !== '' ? null : { code: 'choose' };
		case 'document_date':
			return isDate(value) ? null : { code: 'date' };
		case 'field':
			if (field?.data_type === 'period' && (condition.op === 'gt' || condition.op === 'lt')) {
				return isDate(value) ? null : { code: 'date' };
			}
			return field ? checkFieldValue(field, value) : null;
		default:
			return null;
	}
}

/** What a step condition compares with: a text, a number or true/false; `gt` and `lt` a
 * number or a date; `contains` a text. */
function checkStepValue(op: Operator, value: Value): Problem | null {
	if (op === 'gt' || op === 'lt') {
		return typeof value === 'number' || isDate(value) ? null : { code: 'number' };
	}
	if (op === 'contains') return checkText(value, LIMITS.text);
	if (typeof value === 'boolean' || typeof value === 'number') return null;
	return checkText(value, LIMITS.text);
}

function checkText(value: Value, max: number): Problem | null {
	if (typeof value !== 'string' || value.trim() === '') return { code: 'value' };
	return value.length > max ? { code: 'text_long', params: { max } } : null;
}

function checkFieldValue(field: FieldInfo, value: Value): Problem | null {
	switch (field.data_type) {
		case 'boolean':
			return typeof value === 'boolean' ? null : { code: 'value' };
		case 'amount':
			return isMoney(value) && isNumber(value.amount) && /^[A-Z]{3}$/.test(value.currency)
				? null
				: { code: 'amount' };
		case 'period':
			return isPeriod(value) && isDate(value.start) && isDate(value.end) && value.start <= value.end
				? null
				: { code: 'period' };
		case 'number':
			return isNumber(value) ? null : { code: 'number' };
		case 'date':
			return isDate(value) ? null : { code: 'date' };
		case 'choice':
			return typeof value === 'string' && value !== '' ? null : { code: 'choose' };
		default:
			// Text and links have no length limit as a whole value.
			return checkText(value, Infinity);
	}
}

// --- a field's value as a template ---------------------------------------------------------

/** Where Liquid begins an output or a tag. */
const MARKUP = /\{[{%]/;

/**
 * Whether an action's value for `field` is shown as a template: always for a text field; for
 * the other types, text that is not a fixed value in the field's JSON form (an amount, a
 * period and yes or no are fixed as JSON, a number and a date as their text, a choice as one of
 * its options or text without markup, a link as text without markup). An empty value is a
 * fixed one not given yet. The API takes text as a template for every type (a choice's option
 * as it is) and reads what it writes; the builder decides once, when it shows the action
 * (`SetFieldNode.templated`).
 */
export function isTemplated(field: FieldInfo | null, value: Value): boolean {
	if (typeof value !== 'string') return false;
	if (field?.data_type === 'text') return true;
	if (value === '') return false;
	switch (field?.data_type) {
		case 'boolean':
		case 'amount':
		case 'period':
			return true;
		case 'number':
			return !isNumber(value);
		case 'date':
			return !isDate(value);
		case 'choice':
			return !field.choices.includes(value) && MARKUP.test(value);
		default:
			return MARKUP.test(value);
	}
}

/** A fixed value as the text a template starts from: an amount with its currency, a period in
 * ISO 8601, yes or no as `true` or `false`. */
export function asTemplate(value: Value): string {
	if (typeof value === 'string') return value;
	if (typeof value === 'boolean' || typeof value === 'number') return String(value);
	if (isMoney(value)) return value.amount === '' ? '' : `${value.amount} ${value.currency}`;
	if (isPeriod(value)) return writePeriod(value.start, value.end);
	return '';
}

/** A template's text as a fixed value of `field`, where it is one (`12.50 EUR` an amount, a
 * date as `YYYY-MM-DD`); otherwise the field's empty value. */
export function asFixed(field: FieldInfo, value: Value): Value {
	const text = typeof value === 'string' ? value.trim() : '';
	const empty = defaultValue('field', 'is', field);
	switch (field.data_type) {
		case 'amount': {
			const found = /^(-?\d+(?:\.\d+)?) ?([A-Z]{3})$/.exec(text);
			return found ? { amount: found[1], currency: found[2] } : empty;
		}
		case 'boolean':
			return text === 'false' ? false : empty;
		case 'period':
			return readPeriod(text) ?? empty;
		case 'text':
			return text;
		default:
			return isTemplated(field, text) ? empty : text;
	}
}

/** What the API reads as a finite decimal (Python's `Decimal`: exponent, `_` between digits). */
function isNumber(value: Value): boolean {
	if (typeof value === 'number') return Number.isFinite(value);
	return (
		typeof value === 'string' &&
		/^[+-]?(\d(_?\d)*(\.(\d(_?\d)*)?)?|\.\d(_?\d)*)(e[+-]?\d(_?\d)*)?$/i.test(value.trim())
	);
}

/** What the API reads as a date (Python's `date.fromisoformat`, also `20240115`, `2024-W03-1`). */
function isDate(value: Value): boolean {
	return typeof value === 'string' && /^\d{4}-?(\d{2}-?\d{2}|W\d{2}(-?\d)?)$/.test(value);
}

function checkAction(action: ActionNode, fields: readonly FieldInfo[]): Problem | null {
	switch (action.type) {
		case 'set_space':
			return action.space_id ? null : { code: 'choose' };
		case 'set_contact':
			return action.contact_id ? null : { code: 'choose' };
		case 'set_document_type':
			return action.document_type_id ? null : { code: 'choose' };
		case 'set_topic':
			return action.topic_id ? null : { code: 'choose' };
		case 'set_title':
			return checkText(action.template, LIMITS.text);
		case 'add_tags':
		case 'remove_tags':
			if (action.tag_ids.length === 0) return { code: 'list' };
			return action.tag_ids.length > LIMITS.list
				? { code: 'list_long', params: { max: LIMITS.list } }
				: null;
		case 'set_field': {
			if (!action.field_id) return { code: 'field' };
			const field = fields.find((entry) => entry.id === action.field_id);
			if (!field) return null;
			return (action.templated ?? isTemplated(field, action.value))
				? checkText(action.value, LIMITS.text)
				: checkFieldValue(field, action.value);
		}
		case 'force_review':
			return checkText(action.reason, LIMITS.text);
		case 'send_webhook':
			return action.webhook_id ? null : { code: 'choose' };
		case 'ask_webhook':
			if (!STEP_NAME.test(action.name)) return { code: 'step_name' };
			if (!action.webhook_id) return { code: 'choose' };
			return Number.isInteger(action.timeout_seconds) &&
				action.timeout_seconds >= TIMEOUT.min &&
				action.timeout_seconds <= TIMEOUT.max
				? null
				: { code: 'timeout', params: { min: TIMEOUT.min / 60, max: TIMEOUT.max / 3600 } };
		case 'condition':
			return null;
	}
}
