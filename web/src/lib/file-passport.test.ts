import { describe, expect, it } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import { fileDate, fingerprint, lifeOf, madeWith, saidBy } from '#lib/file-passport.ts';

type Files = components['schemas']['DocumentFilesOut'];
const entry = (source: 'info' | 'xmp' | 'exif', key: string, value: string) => ({
	source,
	key,
	value
});

const pdf = (entries: ReturnType<typeof entry>[]) => ({
	size: 1000,
	sha256: 'ab'.repeat(32),
	metadata: {
		format: 'PDF',
		pdf_version: '1.7',
		pdfa: null,
		width: null,
		height: null,
		dpi: null,
		pages: 1,
		entries
	}
});

describe('fileDate', () => {
	it('reads the dates of a PDF, of XMP and of EXIF, and nothing else', () => {
		expect(fileDate("D:20261001164215+02'00'")?.toISOString()).toBe('2026-10-01T14:42:15.000Z');
		expect(fileDate('D:20261001164215Z')?.toISOString()).toBe('2026-10-01T16:42:15.000Z');
		expect(fileDate('D:2026')?.getFullYear()).toBe(2026);
		expect(fileDate('2026-10-01T16:42:15+02:00')?.toISOString()).toBe('2026-10-01T14:42:15.000Z');
		expect(fileDate('2026:10:01 16:42:15')?.getDate()).toBe(1);
		expect(fileDate('gestern')).toBeNull();
		expect(fileDate('D:20261341')).toBeNull();
		expect(fileDate(null)).toBeNull();
	});
});

describe('the passport of a file', () => {
	it('tells what made it and what it says about itself', () => {
		const { metadata } = pdf([
			entry('info', 'Creator', 'Microsoft Word'),
			entry('info', 'Producer', 'Adobe PDF Library 17'),
			entry('info', 'Title', ' Abschlag '),
			entry('xmp', 'dc:language', 'de-DE')
		]);
		expect(madeWith(metadata)).toEqual({
			creator: 'Microsoft Word',
			producer: 'Adobe PDF Library 17',
			camera: null
		});
		expect(saidBy(metadata)).toEqual([
			['title', 'Abschlag'],
			['language', 'de-DE']
		]);
		// One program for both is said once; a photo names its camera.
		expect(
			madeWith(
				pdf([entry('xmp', 'xmp:CreatorTool', 'Word'), entry('xmp', 'pdf:Producer', 'Word')])
					.metadata
			).producer
		).toBeNull();
		expect(
			madeWith(pdf([entry('exif', 'Make', 'Apple'), entry('exif', 'Model', 'iPhone 15')]).metadata)
				.camera
		).toBe('Apple iPhone 15');
	});

	it('follows its life from the sender to the last change in Lekto', () => {
		const files = {
			added: '2026-10-20T07:13:00Z',
			modified: '2026-10-20T09:02:00Z',
			original_filename: 'brief.pdf',
			media_type: 'application/pdf',
			page_count: 1,
			original: pdf([
				entry('info', 'CreationDate', "D:20261001164215+02'00'"),
				entry('info', 'ModDate', "D:20261001164215+02'00'")
			]),
			archive: pdf([entry('xmp', 'xmp:ModifyDate', '2026-10-20T07:14:02Z')])
		} as unknown as Files;
		expect(lifeOf(files).map((step) => [step.kind, step.outside])).toEqual([
			['created', true],
			['added', false],
			['archived', false],
			['modified', false]
		]);
		// Changed nowhere since: no last step.
		expect(
			lifeOf({ ...files, modified: files.added, archive: null }).map((step) => step.kind)
		).toEqual(['created', 'added']);
	});

	it('draws the same fingerprint for the same file, a mirrored one', () => {
		const sha = '9f2c41d07ab3e65c1f80d29a4c7be3150a6d2f9e84c13b7a5d0e6f21c98b47a3';
		expect(fingerprint(sha)).toEqual(fingerprint(sha.toUpperCase()));
		const { cells } = fingerprint(sha);
		for (const cell of cells) {
			expect(cells.some((other) => other.x === 7 - cell.x && other.y === cell.y)).toBe(true);
		}
		expect(fingerprint('0'.repeat(64)).cells).toEqual([]);
	});
});
