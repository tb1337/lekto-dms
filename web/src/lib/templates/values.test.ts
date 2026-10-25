import { describe, expect, it } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import { templateNames } from './values.ts';

describe('the values of a template', () => {
	it('names the answers of the steps before that ask in a rule', () => {
		const names = templateNames('rule', ['flow']).map((entry) => entry.name);
		expect(names).toContain('steps.flow');
		expect(templateNames('rule', ['flow']).at(-1)?.label).toBe(
			m.template_value_step({ name: 'flow' })
		);
		expect(templateNames('rule').some((entry) => entry.name.startsWith('steps.'))).toBe(false);
	});

	it('gives a webhook the task besides', () => {
		expect(templateNames('webhook').map((entry) => entry.name)).toContain('task.token');
	});
});
