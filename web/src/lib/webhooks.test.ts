import { describe, expect, it } from 'vitest';
import { WEBHOOK_EVENT_TYPES } from '#lib/events.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { eventLabel, selectionVolume, volumeLevel, volumeText } from './webhooks.ts';

describe('how often webhook events come for one document', () => {
	it('says it in words and as a level for every event', () => {
		expect(volumeText('document.filed')).toBe(m.webhook_volume_times({ count: 1 }));
		expect(volumeText('document.node_started')).toBe(m.webhook_volume_run({ count: 13 }));
		expect(volumeText('document.lane_changed')).toBe(m.webhook_volume_range({ least: 2, most: 7 }));
		expect(volumeText('document.deleted')).toBe(m.webhook_volume_at_most_once());
		expect(volumeText('document.moved')).toBe(m.webhook_volume_rare());
		expect(WEBHOOK_EVENT_TYPES.map(volumeLevel)).toContain(3);
		expect([volumeLevel('document.filed'), volumeLevel('document.updated')]).toEqual([1, 2]);
		expect(volumeLevel('document.node_completed')).toBe(3);
	});

	it('adds up the chosen events, and tells how many come from the steps', () => {
		expect(selectionVolume(['document.filed'], false)).toEqual({
			least: 1,
			most: 1,
			steps: { least: 0, most: 0 }
		});
		const all = selectionVolume([], true);
		expect(all).toEqual({ least: 31, most: 75, steps: { least: 26, most: 54 } });
		expect(selectionVolume([...WEBHOOK_EVENT_TYPES], false)).toEqual(all);
	});

	it('names the logged events, an unknown one as it is', () => {
		expect(eventLabel('document.filed')).toBe(m.event_filed());
		expect(eventLabel('rule.send')).toBe(m.event_rule_send());
		expect(eventLabel('external.propose')).toBe(m.webhook_model_call_propose());
		expect(eventLabel('something.new')).toBe('something.new');
	});
});
