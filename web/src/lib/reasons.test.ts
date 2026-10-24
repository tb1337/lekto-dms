// Reasons with codes in the user's language; the API's English where a code is unknown here.
import { afterEach, describe, expect, it } from 'vitest';
import openapi from '../../openapi.json';
import de from '../../messages/de.json';
import en from '../../messages/en.json';
import { getLocale, setLocale } from '#lib/paraglide/runtime.js';
import { REASONS, outputReasonText, reasonText, reasonsText, type Reason } from './reasons.ts';

const catalog = (openapi as unknown as { 'x-reasons': Record<string, Record<string, string>> })[
	'x-reasons'
];
const before = getLocale();
afterEach(() => setLocale(before, { reload: false }));

function placeholders(text: string): string[] {
	return [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1]);
}

describe('the reasons of the API', () => {
	it('each have a message, with only the parameters the API gives, written as it says', () => {
		for (const [code, params] of Object.entries(catalog)) {
			if (code === 'text' || code === 'error') continue;
			const key = `reason_${code}` as keyof typeof en;
			expect(en[key], code).toBeTypeOf('string');
			for (const text of [en[key], de[key as keyof typeof de]]) {
				expect(
					placeholders(text).filter((name) => !(name in params)),
					code
				).toEqual([]);
			}
			const kinds = Object.fromEntries(
				Object.entries(params).filter(([, kind]) => kind !== 'text')
			);
			expect(REASONS[code as keyof typeof REASONS].kinds, code).toEqual(kinds);
		}
		expect(Object.keys(REASONS).sort()).toEqual(
			Object.keys(catalog)
				.filter((code) => code !== 'text' && code !== 'error')
				.sort()
		);
	});
});

describe('a reason in the user language', () => {
	it('writes names, numbers, values and fields as the language does', () => {
		setLocale('de', { reload: false });
		const reason = (code: string, params: Record<string, unknown>, extra = {}): Reason =>
			({ code, params, ...extra }) as Reason;
		expect(reasonText(reason('signals_disagree', { names: ['A', 'B'] }))).toBe(
			'die Signale sind uneins: „A“ oder „B“'
		);
		expect(reasonText(reason('page_poorly_read', { page: 2, share: 0.1834 }))).toBe(
			'Seite 2 wurde schlecht gelesen (18\u00a0% ihrer Wörter unsicher)'
		);
		const values = [
			{ rule: 'Bezahlt', value: true },
			{ rule: 'Offen', value: "'offen'" }
		];
		expect(reasonText(reason('rules_disagree', { values }))).toBe(
			'Regeln setzen verschiedene Werte („Bezahlt“: Ja, „Offen“: „offen“)'
		);
		const widens = reason('space_widens_needs_confirmed', {
			space: 'Familie',
			fields: ['contact', 'document_type']
		});
		expect(reasonText(widens, { field: (name) => ({ contact: 'Kontakt' })[name] ?? name })).toBe(
			'legt nur mit bestätigtem Kontakt und document_type in den Space „Familie“ ab, den mehr Personen sehen'
		);
		expect(reasonText(reason('amount_not_in_text', {}, { subject: 'Betrag', rule: 'Strom' }))).toBe(
			'Regel „Strom“: „Betrag“: der Betrag steht nicht im Text'
		);
		expect(reasonText(reason('text', { text: 'Bitte prüfen' }))).toBe('Bitte prüfen');
	});

	it('writes a reason within a reason, the field a node names and a log output', () => {
		setLocale('de', { reload: false });
		const why = { code: 'no_language_model', params: {} };
		expect(reasonText({ code: 'date_none_from_model', params: { why } } as unknown as Reason)).toBe(
			'kein Datum erkannt: das Sprachmodell hat keins genannt (kein Sprachmodell eingerichtet)'
		);
		const field = { code: 'contact_none', params: {}, field: 'contact' } as Reason;
		expect(reasonText(field, { field: () => 'Kontakt' })).toBe('Kontakt: kein Kontakt erkannt');
		const back = { code: 'rules_back_and_forth', params: { spaces: ['tobi', 'Haushalt', 'tobi'] } };
		expect(outputReasonText(back, 'English')).toBe(
			'Regeln verschieben es hin und her: tobi → Haushalt → tobi'
		);
		expect(outputReasonText(undefined, 'English')).toBe('English');
		expect(outputReasonText(undefined, undefined)).toBeNull();
	});

	it('names things and actions in the user language', () => {
		setLocale('de', { reload: false });
		const reason = (code: string, params: Record<string, unknown>): Reason =>
			({ code, params }) as Reason;
		expect(reasonText(reason('admins_only', { action: 'manage_users' }))).toBe(
			'Nur Admins dürfen Nutzer verwalten.'
		);
		expect(reasonText(reason('not_found', { kind: 'document type', id: 'x1' }))).toBe(
			'Dokumenttyp x1 wurde nicht gefunden.'
		);
		expect(reasonText(reason('name_too_long', { what: 'title', max: 300 }))).toBe(
			'Der Titel darf höchstens 300 Zeichen haben.'
		);
		expect(reasonText(reason('not_found', { kind: 'gizmo', id: 'x2' }))).toBe(
			'gizmo x2 wurde nicht gefunden.'
		);
		expect(
			reasonText(
				reason('tag_wrong_scope', { tag: 'Kfz', scope: 'topic', expected: 'contact group' })
			)
		).toBe('„Kfz“ hat die Art „Thema“, nicht „Kontaktgruppe“.');
		expect(reasonText(reason('password_too_short', { min: 1000 }))).toBe(
			'Das Passwort muss mindestens 1.000 Zeichen haben.'
		);
	});

	it('falls back to the English text without codes or for a code it does not know', () => {
		setLocale('de', { reload: false });
		const known = { code: 'contact_none', params: {} } as Reason;
		const unknown = { code: 'from_the_future', params: {} } as unknown as Reason;
		expect(reasonsText([known, known], 'English')).toBe(
			'kein Kontakt erkannt; kein Kontakt erkannt'
		);
		expect(reasonsText([known, unknown], 'English')).toBe('English');
		expect(reasonsText([], 'English')).toBe('English');
		expect(reasonsText(undefined, null)).toBeNull();
	});
});
