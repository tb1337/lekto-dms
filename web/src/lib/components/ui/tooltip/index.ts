import { Tooltip as TooltipPrimitive } from 'bits-ui';
import Root from './tooltip.svelte';
import Content from './tooltip-content.svelte';

const Trigger = TooltipPrimitive.Trigger;

export {
	Root,
	Trigger,
	Content,
	//
	Root as Tooltip,
	Trigger as TooltipTrigger,
	Content as TooltipContent
};
