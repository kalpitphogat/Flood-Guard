import type { ResultSummary } from '../types/api'
import { formatNumber } from './Value'

/**
 * How the loaded result was produced. A precomputed run is never presented as
 * computed just now, and a quick estimate always says how coarse it is.
 */
export function runModeLabel(summary: Pick<
  ResultSummary,
  'run_mode' | 'completed_utc' | 'resolution_m' | 'duration_hours'
>): string {
  const res = summary.resolution_m !== null ? `${formatNumber(summary.resolution_m, 0)} m` : '— m'
  const hours =
    summary.duration_hours !== null ? `${formatNumber(summary.duration_hours, 0)} h simulated` : null
  if (summary.run_mode === 'precomputed') {
    const date = summary.completed_utc ? summary.completed_utc.slice(0, 10) : '—'
    return [`Precomputed on ${date}`, res, hours].filter(Boolean).join(' · ')
  }
  if (summary.run_mode === 'quick_estimate') {
    return ['Quick estimate', res, hours].filter(Boolean).join(' · ')
  }
  return ['Full run', res, hours].filter(Boolean).join(' · ')
}

export default function RunModeBadge({ summary }: { summary: ResultSummary | undefined }) {
  if (!summary) return null
  const tone =
    summary.run_mode === 'quick_estimate'
      ? 'border-amber-300 bg-amber-50 text-amber-900'
      : summary.run_mode === 'precomputed'
        ? 'border-emerald-300 bg-emerald-50 text-emerald-900'
        : 'border-slate-300 bg-slate-50 text-slate-700'
  return (
    <span
      className={`inline-block rounded border px-2 py-0.5 text-[11px] font-medium ${tone}`}
      data-testid="run-mode-badge"
      title={
        summary.run_mode === 'quick_estimate'
          ? 'Coarse live estimate. Use a precomputed preset or a full CLI run for reportable numbers.'
          : summary.run_mode === 'precomputed'
            ? 'Stored result of a full pipeline run, loaded from disk; nothing was computed just now.'
            : 'Full pipeline run.'
      }
    >
      {runModeLabel(summary)}
    </span>
  )
}
