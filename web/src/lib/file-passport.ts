/**
 * The file passport of the metadata tab (Tobi, 20.10.2026): what a stored file's metadata says
 * in words a person reads. Its dates (a PDF's `D:20261001164215+02'00'`, XMP's ISO dates,
 * EXIF's `2026:10:01 16:42:15`), what made it, what it says about itself, the steps of its life
 * from the sender to Lekto, and a fingerprint of its SHA-256 to tell files apart at a glance.
 * Metadata is someone else's text: whatever cannot be read is left out.
 */
import type { components } from '#lib/api/schema.ts';

type Files = components['schemas']['DocumentFilesOut'];
type Metadata = NonNullable<components['schemas']['StoredFileOut']['metadata']>;
type Entry = Metadata['entries'][number];

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

export type StepKind = 'created' | 'changed' | 'added' | 'archived' | 'modified';

export interface Step {
	kind: StepKind;
	at: Date;
	/** Before Lekto: as the file says, at the sender. */
	outside: boolean;
}

const MINUTE = 60_000;

/** The life of a document's file, in order: made and changed at the sender (as the original
 * says), received, archived (as the archive says), changed in Lekto last. A step as late as
 * the one before it, within a minute, is left out. */
export function lifeOf(files: Files): Step[] {
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
	if (archived && !before(archived, added)) {
		steps.push({ kind: 'archived', at: archived, outside: false });
	}
	if (later(modified, steps.at(-1)!.at))
		steps.push({ kind: 'modified', at: modified, outside: false });
	return steps;
}

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
