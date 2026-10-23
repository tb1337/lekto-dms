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

/** A lane as a filled mark (the band, the dots, the rail of the timeline): the lanes' own
 * hues in light and dark, the light yellow with a darker edge to stand out from the card. */
export const MARK: Record<'green' | 'yellow' | 'red', string> = {
	green: 'bg-lane-green-mark',
	yellow: 'bg-lane-yellow-mark ring-1 ring-lane-yellow-mark-edge ring-inset',
	red: 'bg-lane-red-mark'
};

/** Text written on a lane's mark. */
export const ON_MARK: Record<'green' | 'yellow' | 'red', string> = {
	green: 'text-lane-green-on-mark',
	yellow: 'text-lane-yellow-on-mark',
	red: 'text-lane-red-on-mark'
};

/** A chip in a tone: its ground and text. */
export const TONE_CHIP: Record<Tone, string> = {
	green: 'bg-lane-green text-lane-green-foreground',
	yellow: 'bg-lane-yellow text-lane-yellow-foreground',
	red: 'bg-lane-red text-lane-red-foreground',
	running: 'bg-lane-running text-lane-running-foreground',
	muted: 'bg-muted text-muted-foreground'
};
