/**
 * Values written as chips (a contact's other spellings): what typing or pasting adds.
 */

/** `values` with the lines of `text` after them: trimmed, empty lines and values there already
 * (regardless of case) left out. */
export function addChips(values: readonly string[], text: string): string[] {
	const next = [...values];
	for (const line of text.split('\n')) {
		const value = line.trim();
		const known = next.some((other) => other.toLocaleLowerCase() === value.toLocaleLowerCase());
		if (value !== '' && !known) next.push(value);
	}
	return next;
}
