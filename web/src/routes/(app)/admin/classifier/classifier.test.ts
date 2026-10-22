import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { events } from '#lib/events.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { session } from '#lib/session.svelte.ts';
import Page from './+page.svelte';

const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

function json(status: number, body: unknown, type = 'application/json'): Response {
	return new Response(JSON.stringify(body), { status, headers: { 'content-type': type } });
}

const trained = {
	model: {
		number: 2,
		trained_at: '2026-10-13T12:00:00Z',
		examples: 1515,
		examples_until: '2026-10-13T11:00:00Z',
		classes: { contact: 80, document_type: 16, topic: 4, space: 3, tags: 9 },
		learned_identifiers: 42,
		accuracy: { tested: 303, contact: 0.91, document_type: 0.87 },
		method: 'scikit-learn 1.9.1 lekto-tfidf-logreg/1'
	},
	confirmed: 1520,
	since: 5,
	min_examples: 20,
	retrain_after: 25,
	threshold: 0.8
};

beforeEach(() => {
	session.start({
		user: { id: 'admin', username: 'admin', role: 'admin' },
		method: 'password',
		expires_at: '2026-10-14T12:00:00Z',
		csrf_token: 'token'
	});
	fetchMock.mockReset();
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	session.clear();
	vi.unstubAllGlobals();
});

describe('classifier page', () => {
	it('shows what the model learned and trains on request', async () => {
		fetchMock.mockImplementation(async (request) =>
			request.method === 'POST' ? new Response(null, { status: 202 }) : json(200, trained)
		);
		render(Page);
		expect(await screen.findByText(m.classifier_identifiers({ count: '42' }))).toBeTruthy();
		expect(screen.getByText(m.classifier_next({ since: '5', needed: '25' }))).toBeTruthy();
		await userEvent.click(screen.getByRole('button', { name: m.classifier_train() }));
		const post = fetchMock.mock.calls.map((call) => call[0]).find((call) => call.method === 'POST');
		expect(new URL(post!.url).pathname).toBe('/api/v1/classifier/train');
	});

	it('shows the new model once a training ended', async () => {
		let emit: ((message: { data: string }) => void) | undefined;
		events.useFactory(
			() =>
				({
					addEventListener(type: string, handler: (message: { data: string }) => void) {
						if (type === 'classifier.trained') emit = handler;
					},
					close() {}
				}) as unknown as EventSource
		);
		events.start(() => {});
		let current = trained;
		fetchMock.mockImplementation(async () => json(200, current));
		render(Page);
		expect(await screen.findByText(m.classifier_identifiers({ count: '42' }))).toBeTruthy();

		current = { ...trained, model: { ...trained.model, number: 3, learned_identifiers: 44 } };
		emit?.({
			data: JSON.stringify({ type: 'classifier.trained', id: 'e1', occurred_at: '', number: 3 })
		});
		expect(await screen.findByText(m.classifier_identifiers({ count: '44' }))).toBeTruthy();
		events.stop();
	});

	it('says so when there is no classifier', async () => {
		fetchMock.mockResolvedValue(
			json(
				503,
				{ type: 'about:blank', title: 'Unavailable', status: 503 },
				'application/problem+json'
			)
		);
		render(Page);
		expect(await screen.findByText(m.classifier_not_configured())).toBeTruthy();
		expect(screen.queryByRole('button', { name: m.classifier_train() })).toBeNull();
	});
});
