/**
 * The file passport of the metadata tab (Tobi, 20.10.2026): what a stored file's metadata says
 * in words a person reads. Its dates (a PDF's `D:20261001164215+02'00'`, XMP's ISO dates,
 * EXIF's `2026:10:01 16:42:15`), what made it, what it says about itself, the steps of its life
 * from the sender to Lekto, and a fingerprint of its SHA-256 to tell files apart at a glance.
 * Metadata is someone else's text: whatever cannot be read is left out.
 */
import type { components } from '#lib/api/schema.ts';
import { isIsoDay, isoDayLocal, localDay, pad2 } from '#lib/dates.ts';
import { formatNumber } from '#lib/i18n.ts';

type Files = components['schemas']['DocumentFilesOut'];
type Stored = components['schemas']['StoredFileOut'];
/** What the life needs of the document itself: its lane, its confirmation, its processing. */
export type Reviewed = Pick<
	components['schemas']['DocumentDetails'],
	'lane' | 'confirmed_at' | 'processing' | 'channel' | 'first_lane'
>;
type Metadata = NonNullable<components['schemas']['StoredFileOut']['metadata']>;
type Entry = Metadata['entries'][number];

/** A size as people read it: bytes, kB, MB (decimal, as file managers show them). */
export function fileSize(bytes: number): string {
	const [value, unit] =
		bytes < 1000
			? [bytes, 'byte']
			: bytes < 1_000_000
				? [bytes / 1000, 'kilobyte']
				: [bytes / 1_000_000, 'megabyte'];
	return formatNumber(value, { style: 'unit', unit, maximumFractionDigits: 1 });
}

/** What a file is, in a word: PDF, PDF/A-2B, JPEG; nothing without its metadata. */
export function fileKind(file: Stored): string {
	const metadata = file.metadata;
	if (!metadata) return '';
	return metadata.pdfa ? `PDF/A-${metadata.pdfa}` : metadata.format;
}

/** The value of the first of `keys` the entries have (keys compared regardless of case). */
export function entryValue(entries: readonly Entry[], ...keys: string[]): string | null {
	for (const key of keys) {
		const wanted = key.toLowerCase();
		const found = entries.find((entry) => entry.key.toLowerCase() === wanted);
		if (found && found.value.trim() !== '') return found.value.trim();
	}
	return null;
}

const PDF_DATE =
	/^D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?(?:([Zz+-])(\d{2})?'?(\d{2})?'?)?/;
const EXIF_DATE = /^(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})$/;

/** A date as metadata writes it, or null. */
export function fileDate(text: string | null): Date | null {
	if (!text) return null;
	const value = text.trim();
	const pdf = PDF_DATE.exec(value);
	if (pdf) {
		const [, year, month = '01', day = '01', hour = '00', minute = '00', second = '00'] = pdf;
		const [sign, zoneHours, zoneMinutes] = [pdf[7], pdf[8], pdf[9]];
		const zone =
			sign === undefined
				? ''
				: sign.toUpperCase() === 'Z'
					? 'Z'
					: `${sign}${zoneHours ?? '00'}:${zoneMinutes ?? '00'}`;
		return valid(new Date(`${year}-${month}-${day}T${hour}:${minute}:${second}${zone}`));
	}
	const exif = EXIF_DATE.exec(value);
	if (exif) {
		const [, year, month, day, hour, minute, second] = exif;
		return valid(new Date(`${year}-${month}-${day}T${hour}:${minute}:${second}`));
	}
	// A day alone is a calendar day; a moment with a zone is read as the browser does.
	if (isIsoDay(value)) return valid(localDay(value));
	return /^\d{4}-\d{2}-\d{2}/.test(value) ? valid(new Date(value)) : null;
}

function valid(date: Date): Date | null {
	return Number.isNaN(date.getTime()) ? null : date;
}

/** When the file says it was made, and changed. */
export function madeOn(metadata: Metadata | null): { created: Date | null; changed: Date | null } {
	const entries = metadata?.entries ?? [];
	return {
		created: fileDate(
			entryValue(entries, 'CreationDate', 'xmp:CreateDate', 'DateTimeOriginal', 'DateTime')
		),
		changed: fileDate(entryValue(entries, 'ModDate', 'xmp:ModifyDate', 'DateTime'))
	};
}

/** What made the file: the program it was written with and the one that made it a PDF (or
 * the camera and its software). Null where it says nothing. */
export function madeWith(metadata: Metadata | null): {
	creator: string | null;
	producer: string | null;
	camera: string | null;
} {
	const entries = metadata?.entries ?? [];
	const make = entryValue(entries, 'Make');
	const model = entryValue(entries, 'Model');
	const camera = [make, model && !make?.includes(model) ? model : null].filter(Boolean).join(' ');
	const creator = entryValue(entries, 'Creator', 'xmp:CreatorTool');
	const producer = entryValue(entries, 'Producer', 'pdf:Producer', 'Software');
	return {
		creator,
		producer: producer && producer !== creator ? producer : null,
		camera: camera || null
	};
}

export type SaidKey = 'title' | 'author' | 'subject' | 'keywords' | 'language';

/** What the file says about itself, as far as it does. */
export function saidBy(metadata: Metadata | null): [SaidKey, string][] {
	const entries = metadata?.entries ?? [];
	const said: [SaidKey, string | null][] = [
		['title', entryValue(entries, 'Title', 'dc:title')],
		['author', entryValue(entries, 'Author', 'dc:creator', 'Artist')],
		['subject', entryValue(entries, 'Subject', 'dc:description', 'ImageDescription')],
		['keywords', entryValue(entries, 'Keywords', 'pdf:Keywords', 'dc:subject')],
		['language', entryValue(entries, 'dc:language', 'Lang')]
	];
	return said.filter((entry): entry is [SaidKey, string] => entry[1] !== null);
}

export type StepKind =
	'created' | 'changed' | 'added' | 'archived' | 'confirmed' | 'unreviewed' | 'modified' | 'review';

export interface Step {
	kind: StepKind;
	at: Date;
	/** Before Lekto: as the file says, at the sender. */
	outside: boolean;
	/** Still to come (the review); `at` is now. */
	open?: boolean;
	/** Confirmed with the metadata taken over from the source system, not by a person. */
	takenOver?: boolean;
}

const MINUTE = 60_000;

/** The life of a document's file, in order: made and changed at the sender (as the original
 * says), received, archived (as the archive says), changed in Lekto last. A step as late as
 * the one before it, within a minute, is left out. With the document, the review too (Tobi,
 * 21.10.2026): reviewed by a person (`confirmed_at`), filed by the pipeline without one, or
 * still to come while its lane is yellow or red, at the end. */
export function lifeOf(files: Files, document?: Reviewed, now = new Date()): Step[] {
	const original = madeOn(files.original.metadata);
	const archived = files.archive ? madeOn(files.archive.metadata).changed : null;
	const added = new Date(files.added);
	const modified = new Date(files.modified);
	const steps: Step[] = [];
	if (original.created) steps.push({ kind: 'created', at: original.created, outside: true });
	if (original.changed && (!original.created || later(original.changed, original.created))) {
		steps.push({ kind: 'changed', at: original.changed, outside: true });
	}
	steps.push({ kind: 'added', at: added, outside: false });
	const inLekto: Step[] = [];
	if (archived && !before(archived, added)) {
		inLekto.push({ kind: 'archived', at: archived, outside: false });
	}
	const review = document ? reviewOf(document) : {};
	if (review.done) inLekto.push({ ...review.done, at: notBefore(review.done.at, added) });
	steps.push(...inLekto.sort((a, b) => a.at.getTime() - b.at.getTime()));
	if (later(modified, steps.at(-1)!.at))
		steps.push({ kind: 'modified', at: modified, outside: false });
	if (review.due) steps.push({ kind: 'review', at: now, outside: false, open: true });
	return steps;
}

/** Where the review stands: due (not while the pipeline still runs; a field a person changed
 * meanwhile does not end it), or done, by a person or the pipeline filing it without one. */
function reviewOf(document: Reviewed): { done?: Step; due?: boolean } {
	const running = document.processing.status === 'processing';
	const due = !running && (document.lane === 'yellow' || document.lane === 'red');
	const finished = document.processing.nodes
		.map((node) => (node.finished_at ? new Date(node.finished_at).getTime() : 0))
		.reduce((latest, at) => Math.max(latest, at), 0);
	if (due) return { due };
	if (document.confirmed_at) {
		const at = new Date(document.confirmed_at);
		// A migration confirms in its run; a person later.
		const takenOver = document.channel === 'migration' && !later(at, new Date(finished));
		return { done: { kind: 'confirmed', at, outside: false, takenOver } };
	}
	if (!running && document.lane === 'green' && finished > 0) {
		return { done: { kind: 'unreviewed', at: new Date(finished), outside: false } };
	}
	return {};
}

export type GapUnit = 'minute' | 'hour' | 'day' | 'month' | 'year';

/** How long from one step to the next, in the largest unit that fits once; nothing under a
 * minute. */
export function gapOf(from: Date, to: Date): { value: number; unit: GapUnit } | null {
	const minutes = Math.floor((to.getTime() - from.getTime()) / MINUTE);
	if (minutes < 1) return null;
	const days = minutes / (60 * 24);
	if (days >= 365) return { value: Math.max(1, Math.floor(days / 365.25)), unit: 'year' };
	if (days >= 30) return { value: Math.max(1, Math.floor(days / 30.44)), unit: 'month' };
	if (days >= 1) return { value: Math.floor(days), unit: 'day' };
	if (minutes >= 60) return { value: Math.floor(minutes / 60), unit: 'hour' };
	return { value: minutes, unit: 'minute' };
}

/** A moment as a `datetime-local` field holds it: to the minute, in local time. */
export function localMinute(at: Date): string {
	return `${isoDayLocal(at)}T${pad2(at.getHours())}:${pad2(at.getMinutes())}`;
}

const notBefore = (at: Date, floor: Date) => (at.getTime() < floor.getTime() ? floor : at);
const later = (a: Date, b: Date) => a.getTime() - b.getTime() > MINUTE;
const before = (a: Date, b: Date) => b.getTime() - a.getTime() > MINUTE;

/** The SHA-256 as a pattern of 8 × 8 cells, mirrored like an identicon, and its hue: the same
 * file always looks the same, two files hardly ever alike. */
export function fingerprint(sha256: string): {
	hue: number;
	cells: { x: number; y: number; shade: number }[];
} {
	const hex = sha256
		.toLowerCase()
		.replace(/[^0-9a-f]/g, '')
		.padEnd(64, '0');
	const hue = parseInt(hex.slice(0, 3), 16) % 360;
	const cells: { x: number; y: number; shade: number }[] = [];
	for (let y = 0; y < 8; y++) {
		for (let x = 0; x < 4; x++) {
			const value = parseInt(hex[y * 4 + x + 16], 16);
			if (value < 7) continue;
			const shade = value % 3;
			cells.push({ x, y, shade }, { x: 7 - x, y, shade });
		}
	}
	return { hue, cells };
}
