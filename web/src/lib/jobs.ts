/**
 * The background jobs on the page "System": the names of their kinds and states, and the line
 * that says where a job stands ("for 14s · attempt 1", "waiting for 6m 2s").
 */
import type { components } from '#lib/api/schema.ts';
import { formatDuration } from '#lib/duration.ts';
import { formatDate } from '#lib/i18n.ts';
import { m } from '#lib/paraglide/messages.js';

export type Job = components['schemas']['JobOut'];
export type JobState = components['schemas']['JobState'];
export type KindSummary = components['schemas']['KindSummaryOut'];
export type JobsSummary = components['schemas']['JobsSummaryOut'];
export type KindDurations = components['schemas']['KindDurationsOut'];

export const OPEN_STATES = ['running', 'due', 'planned'] as const satisfies readonly JobState[];
export const STATES = [...OPEN_STATES, 'failed', 'done'] as const satisfies readonly JobState[];

/** The kinds Lekto has; one it does not know here (a newer API) shows as it is named. */
const KINDS: Record<string, () => string> = {
	'pipeline.node': m.job_kind_pipeline_node,
	'pipeline.catch_up': m.job_kind_pipeline_catch_up,
	'pipeline.reparse': m.job_kind_pipeline_reparse,
	'pipeline.facts': m.job_kind_pipeline_facts,
	'search.index': m.job_kind_search_index,
	'search.refresh': m.job_kind_search_refresh,
	'search.reconcile': m.job_kind_search_reconcile,
	'search.rebuild': m.job_kind_search_rebuild,
	'classifier.check': m.job_kind_classifier_check,
	'classifier.train': m.job_kind_classifier_train,
	'contacts.logo': m.job_kind_contacts_logo,
	'webhooks.deliver': m.job_kind_webhooks_deliver,
	'tags.normalise': m.job_kind_tags_normalise,
	'rules.apply': m.job_kind_rules_apply,
	'maintenance.cleanup': m.job_kind_maintenance_cleanup,
	'documents.remove_files': m.job_kind_documents_remove_files
};

export function kindLabel(kind: string): string {
	return Object.hasOwn(KINDS, kind) ? KINDS[kind]() : kind;
}

export const STATE_LABELS: Record<JobState, () => string> = {
	running: m.jobs_state_running,
	due: m.jobs_state_due,
	planned: m.jobs_state_planned,
	failed: m.jobs_state_failed,
	done: m.jobs_state_done
};

/** How many jobs of `summary` stand in `states`. */
export function countOf(summary: KindSummary, states: readonly JobState[]): number {
	return states.reduce((sum, state) => sum + summary[state], 0);
}

/** The jobs of every kind in each state. */
export function totals(kinds: readonly KindSummary[]): Record<JobState, number> {
	const all = { running: 0, due: 0, planned: 0, failed: 0, done: 0 };
	for (const kind of kinds) for (const state of STATES) all[state] += kind[state];
	return all;
}

function seconds(from: string, to: Date): number {
	return Math.max(0, (to.getTime() - new Date(from).getTime()) / 1000);
}

/** Where `job` stands at `now`: how long it runs or waits, when it is due, when it ended. */
export function jobTiming(job: Job, now: Date): string {
	switch (job.state) {
		case 'running':
			return m.jobs_running_for({
				duration: formatDuration(seconds(job.started_at ?? job.run_at, now)),
				attempt: String(job.attempts)
			});
		case 'due':
			return m.jobs_due_for({ duration: formatDuration(seconds(job.run_at, now)) });
		case 'planned': {
			const duration = formatDuration(seconds(now.toISOString(), new Date(job.run_at)));
			return job.attempts > 0
				? m.jobs_planned_in({ attempt: String(job.attempts + 1), duration })
				: m.jobs_planned_first({ duration });
		}
		case 'failed': {
			const date = when(job.finished_at ?? job.run_at);
			return job.attempts === 1
				? m.jobs_failed_after_one({ date })
				: m.jobs_failed_after({ attempt: String(job.attempts), date });
		}
		case 'done':
			return m.jobs_done_at({ date: when(job.finished_at ?? job.run_at) });
	}
}

function when(iso: string): string {
	return formatDate(iso, { dateStyle: 'short', timeStyle: 'short' });
}

/** Whether the workers seem to stand still: jobs are due, and none was started for two minutes
 * (or ever). */
export function workersStill(summary: JobsSummary): boolean {
	const due = totals(summary.kinds).due;
	if (due === 0) return false;
	if (summary.last_started_at === null) return true;
	return seconds(summary.last_started_at, new Date(summary.now)) > 120;
}
