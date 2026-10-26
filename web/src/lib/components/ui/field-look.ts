// The look every field shares (web/DESIGN.md, "Fields"): inputs, text areas, selects, pickers and
// search fields, so that a field looks the same wherever it stands.

/** A control that is the field itself (`input`, `textarea`, `select`, a picker's trigger). */
export const FIELD =
	'w-full min-w-0 rounded-xl border border-input bg-card px-3.5 text-base transition-colors placeholder:text-muted-foreground focus-visible:border-ring disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive md:text-sm dark:bg-input/30';

/** The height of a one-line field. */
export const FIELD_HEIGHT = 'h-11';

/** A frame around an input that has more in it (a magnifier): it takes the focus of the input. */
export const FIELD_FRAME =
	'flex min-w-0 items-center gap-2 rounded-xl border border-input bg-card text-muted-foreground transition-colors focus-within:border-ring dark:bg-input/30';
