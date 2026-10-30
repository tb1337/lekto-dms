// See https://svelte.dev/docs/kit/types#app.d.ts
declare global {
	namespace App {
		// interface Error {}
		// interface Locals {}
		// interface PageData {}
		interface PageState {
			/** The words of the documents' search (`lib/words.ts`), never in the address. */
			words?: string;
		}
		// interface Platform {}
	}
}

export {};
