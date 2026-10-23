/**
 * How a step's state looks in the processing view: icon, label and tone (a lane colour, or
 * running, or muted). A lane is never told by colour alone: the icon and the label carry it.
 */
import Circle from '@lucide/svelte/icons/circle';
import CircleCheck from '@lucide/svelte/icons/circle-check';
import CircleDashed from '@lucide/svelte/icons/circle-dashed';
import LoaderCircle from '@lucide/svelte/icons/loader-circle';
import OctagonX from '@lucide/svelte/icons/octagon-x';
import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
import { m } from '#lib/paraglide/messages.js';
import type { NodeState } from '#lib/pipeline.ts';

export type Tone = 'green' | 'yellow' | 'red' | 'running' | 'muted';

export interface Look {
	icon: typeof Circle;
	label: string;
	tone: Tone;
	spin: boolean;
}

/** The look of a step in its state; null: it did not run in the run shown. */
export function stepLook(state: NodeState | null): Look {
	if (state === null) return { icon: Circle, label: m.log_not_run(), tone: 'muted', spin: false };
	if (state.status === 'running')
		return { icon: LoaderCircle, label: m.node_status_running(), tone: 'running', spin: true };
	if (state.status === 'skipped')
		return { icon: CircleDashed, label: m.node_status_skipped(), tone: 'muted', spin: false };
	if (state.status === 'waiting')
		return { icon: Circle, label: m.node_status_waiting(), tone: 'muted', spin: false };
	if (state.outcome === 'failed')
		return { icon: OctagonX, label: m.outcome_failed(), tone: 'red', spin: false };
	if (state.outcome === 'uncertain')
		return { icon: TriangleAlert, label: m.outcome_uncertain(), tone: 'yellow', spin: false };
	return { icon: CircleCheck, label: m.outcome_ok(), tone: 'green', spin: false };
}

/** Text colour of a tone. */
export const TONE_TEXT: Record<Tone, string> = {
	green: 'text-lane-green-foreground',
	yellow: 'text-lane-yellow-foreground',
	red: 'text-lane-red-foreground',
	running: 'text-lane-running-foreground',
	muted: 'text-muted-foreground'
};

type Lane = 'green' | 'yellow' | 'red';

/** A lane as a mark (the band, the rail of the timeline), drawn like the lane's chip (Tobi,
 * 23.10.2026): its ground, and an edge in its text colour that sets the pale ground of the
 * light theme off the card. */
export const MARK: Record<Lane, string> = {
	green: 'bg-lane-green ring-1 ring-inset ring-lane-green-foreground/35',
	yellow: 'bg-lane-yellow ring-1 ring-inset ring-lane-yellow-foreground/45',
	red: 'bg-lane-red ring-1 ring-inset ring-lane-red-foreground/40'
};

/** A small mark (the matrix, the counts, the dots of the timeline): flat, the lane's ground in
 * a plain border of its text colour; an inner ring looks shaded at that size. */
export const DOT: Record<Lane, string> = {
	green: 'border-[1.5px] border-lane-green-foreground bg-lane-green',
	yellow: 'border-[1.5px] border-lane-yellow-foreground bg-lane-yellow',
	red: 'border-[1.5px] border-lane-red-foreground bg-lane-red'
};

/** A stripe too thin for a ground (the steps beside the longest one in the band): the lane's
 * text colour, softened. */
export const STRIPE: Record<Lane, string> = {
	green: 'bg-lane-green-foreground/45',
	yellow: 'bg-lane-yellow-foreground/60',
	red: 'bg-lane-red-foreground/55'
};

/** Text written on a lane's mark: the chip's text. */
export const ON_MARK: Record<Lane, string> = {
	green: 'text-lane-green-foreground',
	yellow: 'text-lane-yellow-foreground',
	red: 'text-lane-red-foreground'
};

/** The ring of a mark or card that is pointed at, in its tone's text colour. */
export const LIT_RING: Record<Tone, string> = {
	green: 'ring-lane-green-foreground',
	yellow: 'ring-lane-yellow-foreground',
	red: 'ring-lane-red-foreground',
	running: 'ring-lane-running-foreground',
	muted: 'ring-muted-foreground'
};

/** An action in the yellow lane (to the filing question), drawn like the chip. */
export const YELLOW_ACTION =
	'bg-lane-yellow text-lane-yellow-foreground ring-1 ring-inset ring-lane-yellow-foreground/35 hover:bg-lane-yellow/70';

/** A chip in a tone: its ground and text. */
export const TONE_CHIP: Record<Tone, string> = {
	green: 'bg-lane-green text-lane-green-foreground',
	yellow: 'bg-lane-yellow text-lane-yellow-foreground',
	red: 'bg-lane-red text-lane-red-foreground',
	running: 'bg-lane-running text-lane-running-foreground',
	muted: 'bg-muted text-muted-foreground'
};
