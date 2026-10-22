/**
 * Uploads of documents, from the inbox: a few files at a time (the workers set the real limit),
 * one call each, into the uploader's personal space (the API keeps a space and an uploader for
 * scripts and the migration; the UI offers no choice). What came of them stays in
 * this browser until dismissed, lost on reload: uploaded, duplicates with the document they
 * duplicate, skipped with the reason (another type, hidden, too large), failed with the error.
 * An uploaded document stands in the inbox from its arrival on, with its progress.
 */
import { api } from '#lib/api/client.ts';
import { apiError, ApiError } from '#lib/api/problem.ts';
import { describeError } from '#lib/errors.ts';
import type { Intake, SkipReason } from '#lib/intake.ts';

export type UploadState = 'waiting' | 'uploading' | 'uploaded' | 'duplicate' | 'skipped' | 'failed';

export interface Upload {
	key: number;
	/** The file's name, within a dropped folder its path there. */
	name: string;
	state: UploadState;
	/** The new document, or for a duplicate the one already there. */
	documentId: string | null;
	reason: SkipReason | null;
	/** Why it failed. */
	message: string | null;
}

/** Requests at the same time. */
export const PARALLEL = 3;

const PENDING: readonly UploadState[] = ['waiting', 'uploading'];

export class Uploads {
	items = $state<Upload[]>([]);
	#queue: { upload: Upload; file: File }[] = [];
	#running = 0;
	#next = 1;

	get active(): boolean {
		return this.items.some((item) => PENDING.includes(item.state));
	}

	/** How many came to what; `done` counts every file no longer waiting or on its way. */
	get counts() {
		const count = (state: UploadState) => this.items.filter((item) => item.state === state).length;
		const pending = count('waiting') + count('uploading');
		return {
			uploaded: count('uploaded'),
			duplicates: count('duplicate'),
			skipped: count('skipped'),
			failed: count('failed'),
			done: this.items.length - pending,
			total: this.items.length
		};
	}

	add(intake: Intake): void {
		for (const skipped of intake.skipped) {
			this.#push({ name: skipped.name, state: 'skipped', reason: skipped.reason });
		}
		for (const { file, name } of intake.files) {
			// The pushed item is a proxy; keep working on that one so the page sees the changes.
			const upload = this.#push({ name, state: 'waiting' });
			this.#queue.push({ upload, file });
		}
		this.#pump();
	}

	/** Forget what is finished; files still on their way stay. */
	dismiss(): void {
		this.items = this.items.filter((item) => PENDING.includes(item.state));
	}

	/** Forget everything: another person may sign in next in this browser. */
	reset(): void {
		this.#queue = [];
		this.items = [];
	}

	#push(fields: Pick<Upload, 'name' | 'state'> & Partial<Upload>): Upload {
		this.items.push({
			key: this.#next++,
			documentId: null,
			reason: null,
			message: null,
			...fields
		});
		return this.items[this.items.length - 1];
	}

	#pump(): void {
		while (this.#running < PARALLEL && this.#queue.length > 0) {
			const job = this.#queue.shift()!;
			this.#running++;
			void this.#send(job.upload, job.file).finally(() => {
				this.#running--;
				this.#pump();
			});
		}
	}

	async #send(upload: Upload, file: File): Promise<void> {
		upload.state = 'uploading';
		const form = new FormData();
		form.append('file', file, file.name);
		try {
			const { data, error, response } = await api.POST('/api/v1/documents', {
				// The generated type wants a string for the file; the form carries the binary.
				body: { file: '' },
				bodySerializer: () => form
			});
			if (!data) throw await apiError(response, error);
			upload.documentId = data.id;
			upload.state = 'uploaded';
		} catch (error) {
			if (error instanceof ApiError && error.status === 409) {
				// Every file exists once per installation; without an id it lies in a space the
				// caller cannot see.
				upload.state = 'duplicate';
				upload.documentId = error.problem?.existing_document_id ?? null;
			} else if (error instanceof ApiError && (error.status === 413 || error.status === 415)) {
				upload.state = 'skipped';
				upload.reason = error.status === 413 ? 'too_large' : 'type';
			} else {
				upload.state = 'failed';
				upload.message = describeError(error);
			}
		}
	}
}

export const uploads = new Uploads();
