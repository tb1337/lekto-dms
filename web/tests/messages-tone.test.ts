// The German texts follow `DESIGN.md` ("Texts"): they address the user with the polite "Du" with
// a capital D, never with "Sie" and never with a lowercase "du", and a form is saved with
// "Speichern", not "Sichern".
import { describe, expect, it } from 'vitest';
import de from '../messages/de.json';

const catalogue: Record<string, string> = de;

const FORMAL = /\b(Sie|Ihr|Ihre|Ihren|Ihrem|Ihrer|Ihres|Ihnen)\b/;
const LOWERCASE_INFORMAL =
	/\b(du|dich|dir|dein|deine|deinen|deinem|deiner|deines|deins|euch|euer|eure|euren|eurem|eurer)\b/;
// The button word; "sichern" in a sentence ("Jetzt sichern": keep it safe) is another verb.
const SICHERN = /\bSichern\b/;

// Keys whose "Sie"/"Ihr" is not an address of the user. This list may only shrink.
const FORMAL_ALLOWED = new Set([
	// The headings „Ihr Zeichen“ and „Ihr Schreiben vom“ as they stand in a letter.
	'identifier_kind_your_reference',
	'identifier_kind_letter_date'
]);

function keys(): string[] {
	return Object.keys(catalogue).filter((key) => key !== '$schema');
}

function matching(pattern: RegExp, allowed: Set<string> = new Set()): string[] {
	return keys().filter((key) => !allowed.has(key) && pattern.test(catalogue[key]));
}

describe('German texts', () => {
	it('address the user without "Sie"', () => {
		expect(matching(FORMAL, FORMAL_ALLOWED)).toEqual([]);
	});

	it('write Du, Dich, Dir and Dein with a capital letter', () => {
		expect(matching(LOWERCASE_INFORMAL)).toEqual([]);
	});

	it('say "Speichern", not "Sichern"', () => {
		expect(matching(SICHERN)).toEqual([]);
	});

	it('keep allowlisted keys that still need it', () => {
		const needless = [...FORMAL_ALLOWED].filter(
			(key) => !(key in catalogue) || !FORMAL.test(catalogue[key])
		);
		expect(needless).toEqual([]);
	});

	it('notice a formal or lowercase address', () => {
		expect(FORMAL.test('Melden Sie sich an.')).toBe(true);
		expect(FORMAL.test('Ihr Konto ist verknüpft.')).toBe(true);
		expect(LOWERCASE_INFORMAL.test('Bitte melde dich an.')).toBe(true);
		expect(LOWERCASE_INFORMAL.test('Nur du')).toBe(true);
		expect(LOWERCASE_INFORMAL.test('Bitte melde Dich an. Dein Konto, Deine Spaces.')).toBe(false);
		expect(FORMAL.test('Die Dokumente ihres Eingangs')).toBe(false);
		expect(SICHERN.test('Sichern')).toBe(true);
		expect(SICHERN.test('Speichern')).toBe(false);
	});
});
