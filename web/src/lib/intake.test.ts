import { describe, expect, it } from 'vitest';
import { ACCEPT, intakeOf, readDrop, skipReason } from './intake.ts';

const pdf = (name: string) => new File(['%PDF-1.7'], name, { type: 'application/pdf' });
const text = (name: string) => new File(['hello'], name, { type: 'text/plain' });

type Entry = FileSystemEntry & { children?: Entry[] };

function fileEntry(path: string, file: File): Entry {
	return {
		isFile: true,
		isDirectory: false,
		name: file.name,
		fullPath: path,
		file: (resolve: (file: File) => void) => resolve(file)
	} as unknown as Entry;
}

/** A folder whose reader answers in batches of `batch`, as browsers do (100 in Chrome). */
function folder(path: string, children: Entry[], batch = 2): Entry & { reads: number } {
	const entry = {
		isFile: false,
		isDirectory: true,
		name: path.slice(path.lastIndexOf('/') + 1),
		fullPath: path,
		reads: 0,
		createReader() {
			let offset = 0;
			return {
				readEntries(resolve: (entries: Entry[]) => void) {
					entry.reads++;
					resolve(children.slice(offset, offset + batch));
					offset += batch;
				}
			};
		}
	};
	return entry as unknown as Entry & { reads: number };
}

function transfer(entries: Entry[]): DataTransfer {
	return {
		items: entries.map((entry) => ({ kind: 'file', webkitGetAsEntry: () => entry })),
		files: []
	} as unknown as DataTransfer;
}

describe('what is skipped', () => {
	it('takes what the API takes, by type or, without one, by ending', () => {
		expect(skipReason('scan.pdf', 'application/pdf')).toBeNull();
		expect(skipReason('photo.JPG', 'image/jpeg')).toBeNull();
		expect(skipReason('fax.tiff', '')).toBeNull();
		expect(skipReason('scan.PDF', 'application/octet-stream')).toBeNull();
		expect(skipReason('notes.txt', 'text/plain')).toBe('type');
		expect(skipReason('photo.heic', 'image/heic')).toBe('type');
		expect(skipReason('README', '')).toBe('type');
		expect(ACCEPT).toBe('application/pdf,image/jpeg,image/png,image/tiff');
	});

	it('skips hidden files', () => {
		expect(skipReason('.DS_Store', '')).toBe('hidden');
		expect(skipReason('.scan.pdf', 'application/pdf')).toBe('hidden');
	});

	it('sorts chosen files', () => {
		expect(intakeOf([pdf('a.pdf'), text('b.txt')])).toEqual({
			files: [{ file: expect.any(File), name: 'a.pdf' }],
			skipped: [{ name: 'b.txt', reason: 'type' }]
		});
	});
});

describe('a drop', () => {
	it('reads folders in full and recursively, without their structure', async () => {
		const inner = folder('/Scans/2026', [
			fileEntry('/Scans/2026/c.pdf', pdf('c.pdf')),
			fileEntry('/Scans/2026/.DS_Store', new File([''], '.DS_Store'))
		]);
		const outer = folder('/Scans', [
			fileEntry('/Scans/a.pdf', pdf('a.pdf')),
			fileEntry('/Scans/notes.txt', text('notes.txt')),
			inner,
			fileEntry('/Scans/b.pdf', pdf('b.pdf')),
			folder('/Scans/.git', [fileEntry('/Scans/.git/HEAD', text('HEAD'))])
		]);
		const found = await readDrop(transfer([outer, fileEntry('/d.pdf', pdf('d.pdf'))]));
		expect(found.files.map((entry) => entry.name)).toEqual([
			'Scans/a.pdf',
			'Scans/2026/c.pdf',
			'Scans/b.pdf',
			'd.pdf'
		]);
		expect(found.files.map((entry) => entry.file.name)).toEqual([
			'a.pdf',
			'c.pdf',
			'b.pdf',
			'd.pdf'
		]);
		expect(found.skipped).toEqual([
			{ name: 'Scans/notes.txt', reason: 'type' },
			{ name: 'Scans/2026/.DS_Store', reason: 'hidden' },
			{ name: 'Scans/.git/', reason: 'hidden' }
		]);
		// Five entries in batches of two: three batches and the empty one that ends it.
		expect(outer.reads).toBe(4);
	});

	it('skips what cannot be read and keeps the rest of the drop', async () => {
		const gone = {
			...fileEntry('/Scans/gone.pdf', pdf('gone.pdf')),
			file: (_: unknown, reject: (error: Error) => void) => reject(new Error('NotFoundError'))
		} as unknown as Entry;
		const locked = {
			...folder('/Scans/locked', []),
			createReader: () => ({
				readEntries: (_: unknown, reject: (error: Error) => void) =>
					reject(new Error('NotReadableError'))
			})
		} as unknown as Entry;
		const found = await readDrop(
			transfer([folder('/Scans', [fileEntry('/Scans/a.pdf', pdf('a.pdf')), gone, locked])])
		);
		expect(found.files.map((entry) => entry.name)).toEqual(['Scans/a.pdf']);
		expect(found.skipped).toEqual([
			{ name: 'Scans/gone.pdf', reason: 'unreadable' },
			{ name: 'Scans/locked/', reason: 'unreadable' }
		]);
	});

	it('takes the files of a browser without entries', async () => {
		const found = await readDrop({
			items: [],
			files: [pdf('a.pdf'), text('b.txt')]
		} as unknown as DataTransfer);
		expect(found.files.map((entry) => entry.name)).toEqual(['a.pdf']);
		expect(found.skipped).toEqual([{ name: 'b.txt', reason: 'type' }]);
	});

	it('takes the entries while the drop runs', () => {
		let taken = false;
		const entry = fileEntry('/a.pdf', pdf('a.pdf'));
		void readDrop({
			items: [
				{
					kind: 'file',
					webkitGetAsEntry: () => {
						taken = true;
						return entry;
					}
				}
			],
			files: []
		} as unknown as DataTransfer);
		expect(taken).toBe(true);
	});
});
