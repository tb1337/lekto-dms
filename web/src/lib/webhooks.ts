// What the webhook pages share: sending a test delivery and telling how it went.
import { toast } from 'svelte-sonner';
import { api } from '#lib/api/client.ts';
import { unwrap } from '#lib/api/call.ts';
import { reportError } from '#lib/errors.ts';
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
