// See https://svelte.dev/docs/kit/types#app.d.ts
declare global {
	namespace App {
		// interface Error {}
		// interface Locals {}
		// interface PageData {}
		interface PageState {
			/** The words of the documents' search (`lib/words.ts`), never in the address. */
			words?: string;
			/** The open Beam (`lib/beam.svelte.ts`). */
			beam?: import('#lib/beam.svelte.ts').BeamState;
			/** The place a jump came from (`lib/way-back.ts`). */
			from?: { label: string };
		}
		// interface Platform {}
	}
}

export {};
