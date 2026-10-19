/**
 * What becomes of files someone chose or dropped to upload: the ones the API takes (PDF, JPEG,
 * PNG, TIFF, as `POST /documents` reads them), and the ones skipped, with the reason. A drop may
 * hold folders: they are read through the browser's entries (`webkitGetAsEntry`), in full and
 * recursively; their structure is not kept. Hidden files and folders (a name starting with a
 * dot, such as `.DS_Store`) are skipped.
 */

/** The media types the API takes, with the endings a file of each may have. */
const ACCEPTED: Record<string, readonly string[]> = {
	'application/pdf': ['pdf'],
	'image/jpeg': ['jpg', 'jpeg'],
	'image/png': ['png'],
	'image/tiff': ['tif', 'tiff']
};

/** For the `accept` of a file input. */
export const ACCEPT = Object.keys(ACCEPTED).join(',');

/** Why a file is not uploaded: another type, hidden, larger than the API takes (413), or the
 * browser could not read it (a folder without permission, a file gone meanwhile). */
export type SkipReason = 'type' | 'hidden' | 'too_large' | 'unreadable';

export interface Skipped {
	/** The file's name, within a dropped folder its path there. */
	name: string;
	reason: SkipReason;
}

export interface Intake {
	files: { file: File; name: string }[];
	skipped: Skipped[];
}

function isHidden(name: string): boolean {
	return name.startsWith('.');
}

/** Why a file is skipped before it is sent; null if it goes. The type counts as the browser
 * names it, or, where it names none it knows, by the ending. */
export function skipReason(name: string, type: string): SkipReason | null {
	if (isHidden(name)) return 'hidden';
	if (type in ACCEPTED) return null;
	const ending = name.includes('.') ? name.slice(name.lastIndexOf('.') + 1).toLowerCase() : '';
	const unnamed = type === '' || type === 'application/octet-stream';
	return unnamed && Object.values(ACCEPTED).some((endings) => endings.includes(ending))
		? null
		: 'type';
}

function sort(found: Intake, file: File, name: string): void {
	const reason = skipReason(file.name, file.type);
	if (reason) found.skipped.push({ name, reason });
	else found.files.push({ file, name });
}

/** Files chosen in a file input. */
export function intakeOf(files: Iterable<File>): Intake {
	const found: Intake = { files: [], skipped: [] };
	for (const file of files) sort(found, file, file.name);
	return found;
}

/** All entries of a folder: `readEntries` answers in batches until one is empty. */
async function entriesIn(directory: FileSystemDirectoryEntry): Promise<FileSystemEntry[]> {
	const reader = directory.createReader();
	const all: FileSystemEntry[] = [];
	for (;;) {
		const batch = await new Promise<FileSystemEntry[]>((resolve, reject) =>
			reader.readEntries(resolve, reject)
		);
		if (batch.length === 0) return all;
		all.push(...batch);
	}
}

async function walk(entry: FileSystemEntry, found: Intake): Promise<void> {
	const name = entry.fullPath.replace(/^\//, '') || entry.name;
	if (entry.isDirectory) {
		// A hidden folder is skipped as one, without reading it (`.git` holds thousands).
		if (isHidden(entry.name)) {
			found.skipped.push({ name: `${name}/`, reason: 'hidden' });
			return;
		}
		let children: FileSystemEntry[];
		try {
			children = await entriesIn(entry as FileSystemDirectoryEntry);
		} catch {
			// One unreadable folder leaves the rest of the drop as it is.
			found.skipped.push({ name: `${name}/`, reason: 'unreadable' });
			return;
		}
		for (const child of children) await walk(child, found);
	} else if (entry.isFile) {
		let file: File;
		try {
			file = await new Promise<File>((resolve, reject) =>
				(entry as FileSystemFileEntry).file(resolve, reject)
			);
		} catch {
			found.skipped.push({ name, reason: 'unreadable' });
			return;
		}
		sort(found, file, name);
	}
}

/**
 * What a drop holds: its files, and the files in its folders. The entries are taken at once,
 * while the drop event runs (the browser empties the transfer afterwards); where the browser
 * has no entries, its files alone count.
 */
export function readDrop(transfer: DataTransfer): Promise<Intake> {
	const items = [...(transfer.items ?? [])].filter((item) => item.kind === 'file');
	const roots: (FileSystemEntry | File)[] = [];
	if (items.length > 0 && items.every((item) => typeof item.webkitGetAsEntry === 'function')) {
		for (const item of items) {
			const entry = item.webkitGetAsEntry();
			const file = entry ? null : item.getAsFile();
			if (entry) roots.push(entry);
			else if (file) roots.push(file);
		}
	} else {
		roots.push(...transfer.files);
	}
	return (async () => {
		const found: Intake = { files: [], skipped: [] };
		for (const root of roots) {
			if (root instanceof File) sort(found, root, root.name);
			else await walk(root, found);
		}
		return found;
	})();
}
