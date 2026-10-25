import { describe, expect, it } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import type { NodeState } from '#lib/pipeline.ts';
import { delegatedLabel, stepLook } from './step-look.ts';

const NOW = new Date('2026-10-25T12:00:00Z');

function delegated(deadline: string | null): NodeState {
	return {
		node: 'apply_rules',
		status: 'delegated',
		outcome: null,
		started_at: '2026-10-25T11:58:00Z',
		finished_at: null,
		deadline
	};
}

describe('a node running externally', () => {
	it('says how many minutes are left, rounded up', () => {
		expect(delegatedLabel(delegated('2026-10-25T12:07:30Z'), NOW)).toBe(
			m.node_status_delegated_left({ minutes: '8' })
		);
		expect(delegatedLabel(delegated('2026-10-25T11:59:00Z'), NOW)).toBe(
			m.node_status_delegated_left({ minutes: '1' })
		);
	});

	it('names no time while its tasks wait to be sent', () => {
		expect(delegatedLabel(delegated(null), NOW)).toBe(m.node_status_delegated());
	});

	it('looks like a node at work, without spinning', () => {
		expect(stepLook(delegated(null))).toMatchObject({ tone: 'running', spin: false });
	});
});
