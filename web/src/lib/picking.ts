/**
 * What the pickers share: a choice of several values turned on or off, and a typed query held
 * against the labels of the options.
 */

/** `selected` with `value` in it (`on`) or without it. */
export function toggled(selected: readonly string[], value: string, on: boolean): string[] {
	return on ? [...selected, value] : selected.filter((entry) => entry !== value);
}

/** `selected` with `value` taken out if it is in it, else added: a chip tapped. */
export function flipped(selected: readonly string[], value: string): string[] {
	return toggled(selected, value, !selected.includes(value));
}

/** A query as it is held against the options: trimmed, regardless of case. */
export function searchWords(query: string): string {
	return query.trim().toLocaleLowerCase();
}

/** Whether `text` holds `words` (from `searchWords`); no words match everything. */
export function matchesWords(text: string, words: string): boolean {
	return text.toLocaleLowerCase().includes(words);
}
