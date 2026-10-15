/**
 * Reading a document with the vision language model (`POST /documents/{id}/vision`): when a
 * person may ask for it, and why it is advised (`GET /documents/{id}/reading`). Only a person
 * asks; the page images leave for the endpoint `GET /pipeline` names.
 */
import type { components } from '#lib/api/schema.ts';
import { m } from '#lib/paraglide/messages.js';
import { reprocessable, type GraphNode, type Processing } from '#lib/pipeline.ts';

export type Vision = components['schemas']['VisionOut'];
export type Reading = components['schemas']['ReadingOut'];

/**
 * Whether the document can be read with the model now: one is configured, nothing is being
 * processed, and processing may start again from OCR (not past a failed node).
 */
export function visionAvailable(
	vision: Vision | null,
	graph: readonly GraphNode[],
	processing: Processing
): boolean {
	return (
		vision !== null &&
		processing.status !== 'processing' &&
		reprocessable(graph, processing).includes('ocr')
	);
}

/** Why reading the document with the model is advised, in words; null if it is not. */
export function adviceText(reading: Reading | null): string | null {
	if (!reading?.advice) return null;
	if (reading.advice === 'no_text') return m.vision_advice_no_text();
	const pages = reading.pages.filter((page) => page.poor).map((page) => page.page);
	return m.vision_advice_poor_page({ pages: pages.join(', ') });
}
