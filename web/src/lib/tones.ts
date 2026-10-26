/**
 * The tones of the UI (web/DESIGN.md, "Colour roles"): the lanes, what is still running, notes,
 * muted facts, the accent for what runs now, and the "Beta" pill. The one map from a tone to its
 * classes: components take a tone and never write the classes themselves. A mark of a tone has
 * its ground, its text in the tone's text colour and an edge in that colour; in the light theme
 * there are no dark fills.
 */
export type Tone = 'green' | 'yellow' | 'red' | 'running' | 'muted' | 'note' | 'primary' | 'beta';

/** The three lanes of a document. */
export type Lane = 'green' | 'yellow' | 'red';

/** Ground and text of a tone. */
export const TONE_FILL: Record<Tone, string> = {
	green: 'bg-lane-green text-lane-green-foreground',
	yellow: 'bg-lane-yellow text-lane-yellow-foreground',
	red: 'bg-lane-red text-lane-red-foreground',
	running: 'bg-lane-running text-lane-running-foreground',
	muted: 'bg-muted text-muted-foreground',
	note: 'bg-note text-note-foreground',
	primary: 'bg-primary/10 text-brand',
	beta: 'bg-beta text-beta-foreground'
};

/** The edge of a tone's mark, in its text colour, so a pale ground stands off the card. */
export const TONE_EDGE: Record<Tone, string> = {
	green: 'border-lane-green-foreground/30',
	yellow: 'border-lane-yellow-foreground/35',
	red: 'border-lane-red-foreground/30',
	running: 'border-lane-running-foreground/25',
	muted: 'border-transparent',
	note: 'border-note-foreground/25',
	primary: 'border-primary/30',
	beta: 'border-beta-foreground/20'
};

/** Text in a tone's colour. */
export const TONE_TEXT: Record<Tone, string> = {
	green: 'text-lane-green-foreground',
	yellow: 'text-lane-yellow-foreground',
	red: 'text-lane-red-foreground',
	running: 'text-lane-running-foreground',
	muted: 'text-muted-foreground',
	note: 'text-note-foreground',
	primary: 'text-brand',
	beta: 'text-beta-foreground'
};

/** A lane's tone; a document without a lane is still being processed. */
export function laneTone(lane: Lane | null | undefined): Tone {
	return lane ?? 'running';
}
