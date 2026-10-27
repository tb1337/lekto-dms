/**
 * The background jobs on the page "System": the names of their kinds and states, and what the
 * table says of each ("6s ago", "in 25s · attempt 2", how long it waited and ran).
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
	'pipeline.relate': m.job_kind_pipeline_relate,
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

/** When `job` is or was due, as the table's column "Due" / "Failed" / "Done" says it: a running
 * job by the time it fell due; a due one "6s ago"; a planned one "in 25s · attempt 2"; a failed
 * or done one by when it ended. */
export function jobDue(job: Job, now: Date): string {
	switch (job.state) {
		case 'running':
			return when(job.run_at);
		case 'due':
			return m.jobs_since({ duration: formatDuration(seconds(job.run_at, now)) });
		case 'planned': {
			const duration = formatDuration(seconds(now.toISOString(), new Date(job.run_at)));
			return job.attempts > 0
				? m.jobs_in_attempt({ attempt: String(job.attempts + 1), duration })
				: m.jobs_in({ duration });
		}
		case 'failed':
		case 'done':
			return when(job.finished_at ?? job.run_at);
	}
}

/** How long `job` waited for a worker: from due to started, so far for a due one; "–" for a
 * planned one. */
export function jobWait(job: Job, now: Date): string {
	if (job.state === 'due')
		return m.jobs_so_far({ duration: formatDuration(seconds(job.run_at, now)) });
	if (job.state === 'planned' || !job.started_at) return '–';
	return formatDuration(seconds(job.run_at, new Date(job.started_at)));
}

/** How long `job` ran: from started to finished, so far for a running one; "–" before it
 * started. */
export function jobRun(job: Job, now: Date): string {
	if (!job.started_at) return '–';
	if (job.state === 'running') {
		return m.jobs_so_far({ duration: formatDuration(seconds(job.started_at, now)) });
	}
	if (!job.finished_at) return '–';
	return formatDuration(seconds(job.started_at, new Date(job.finished_at)));
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
