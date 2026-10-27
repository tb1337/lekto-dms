// What the webhook pages share: sending a test delivery and telling how it went, and the names
// of the events a webhook reports or logs.
import { toast } from 'svelte-sonner';
import { api } from '#lib/api/client.ts';
import { unwrap } from '#lib/api/call.ts';
import { reportError } from '#lib/errors.ts';
import { WEBHOOK_EVENT_TYPES, type WebhookEventType } from '#lib/events.svelte.ts';
import { m } from '#lib/paraglide/messages.js';

/** Send a test event through the webhook; the outcome is a toast. */
export async function sendTest(id: string): Promise<void> {
	try {
		const delivery = await unwrap(
			api.POST('/api/v1/webhooks/{id}/test', { params: { path: { id } } })
		);
		if (delivery.outcome === 'delivered')
			toast.success(m.webhook_test_ok({ status: delivery.status_code ?? 0 }));
		else
			toast.error(
				m.webhook_test_failed({ reason: delivery.error ?? String(delivery.status_code ?? '') })
			);
	} catch (error) {
		reportError(error);
	}
}

/** The events a webhook may report, by name. */
export const EVENT_LABELS: Record<WebhookEventType, () => string> = {
	'document.received': m.event_received,
	'document.node_started': m.event_node_started,
	'document.node_deferred': m.event_node_deferred,
	'document.node_delegated': m.event_node_delegated,
	'document.node_completed': m.event_node_completed,
	'document.lane_changed': m.event_lane_changed,
	'document.filed': m.event_filed,
	'document.updated': m.event_updated,
	'document.deleted': m.event_deleted,
	'document.review_required': m.event_review_required,
	'document.confirmed': m.event_confirmed,
	'document.moved': m.event_moved
};

// What else the log of a webhook holds: a test, a rule sending or asking, a model call.
const LOGGED_LABELS: Record<string, () => string> = {
	'webhook.test': m.event_test,
	'rule.send': m.event_rule_send,
	'rule.ask': m.event_rule_ask,
	'external.propose': m.webhook_model_call_propose,
	'external.extract': m.webhook_model_call_extract
};

/** The name of an event in the log of a webhook; an unknown one as it is. */
export function eventLabel(type: string): string {
	const label = EVENT_LABELS[type as WebhookEventType] ?? LOGGED_LABELS[type];
	return label ? label() : type;
}

/** How often an event typically comes for one document: at least and at most; `run` for the
 * steps, which come once in every processing run (13 steps; a document runs once or twice). */
interface Volume {
	least: number;
	most: number;
	run?: boolean;
}

// From how processing goes and what a fresh document sent to a webhook (Tobi, 27.10.2026):
// 1 received, 26 steps started and 27 done, 7 lane changes, 4 updates, 3 reviews, 2 confirmed.
const STEPS = 13;
export const EVENT_VOLUME: Record<WebhookEventType, Volume> = {
	'document.received': { least: 1, most: 1 },
	'document.node_started': { least: STEPS, most: 2 * STEPS, run: true },
	'document.node_deferred': { least: 0, most: 1 },
	'document.node_delegated': { least: 0, most: 1 },
	'document.node_completed': { least: STEPS, most: 2 * STEPS, run: true },
	'document.lane_changed': { least: 2, most: 7 },
	'document.filed': { least: 1, most: 1 },
	'document.updated': { least: 1, most: 5 },
	'document.deleted': { least: 0, most: 1 },
	'document.review_required': { least: 0, most: 3 },
	'document.confirmed': { least: 0, most: 2 },
	'document.moved': { least: 0, most: 1 }
};

/** How often an event comes for one document, in words: "1×", "2–7×", "≈ 13× per run". */
export function volumeText(type: WebhookEventType): string {
	const { least, most, run } = EVENT_VOLUME[type];
	if (run) return m.webhook_volume_run({ count: least });
	if (least === most) return m.webhook_volume_times({ count: least });
	if (most <= 1)
		return type === 'document.deleted' ? m.webhook_volume_at_most_once() : m.webhook_volume_rare();
	return m.webhook_volume_range({ least, most });
}

/** How loud an event is for one document, for `VolumeMeter`: 1 at most once, 2 a few times,
 * 3 a dozen or more. */
export function volumeLevel(type: WebhookEventType): 1 | 2 | 3 {
	const { most } = EVENT_VOLUME[type];
	return most <= 1 ? 1 : most <= 7 ? 2 : 3;
}

/** How many deliveries `types` bring for one document, at least and at most, and how many of
 * them come from the steps; every event for `all`. */
export function selectionVolume(
	types: readonly string[],
	all: boolean
): { least: number; most: number; steps: { least: number; most: number } } {
	const chosen = WEBHOOK_EVENT_TYPES.filter((type) => all || types.includes(type));
	const total = { least: 0, most: 0, steps: { least: 0, most: 0 } };
	for (const type of chosen) {
		const { least, most } = EVENT_VOLUME[type];
		total.least += least;
		total.most += most;
		if (type.startsWith('document.node_')) {
			total.steps.least += least;
			total.steps.most += most;
		}
	}
	return total;
}
