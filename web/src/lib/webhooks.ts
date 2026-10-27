// What the webhook pages share: sending a test delivery and telling how it went, and the names
// of the events a webhook reports or logs.
import { toast } from 'svelte-sonner';
import { api } from '#lib/api/client.ts';
import { unwrap } from '#lib/api/call.ts';
import { reportError } from '#lib/errors.ts';
import type { WebhookEventType } from '#lib/events.svelte.ts';
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
