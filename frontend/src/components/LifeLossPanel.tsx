import { useState } from 'react'
import { useLifeLoss } from '../api/hooks'
import { Panel, Skeleton, formatNumber } from './Value'

/** Warning-issue assumptions offered, from Graham (1999) Table 2 (earthfill dams). */
const WARNING_CHOICES: Array<{ value: number; label: string }> = [
  { value: -60, label: '1 h before breach (day, observers at dam)' },
  { value: 0, label: 'When the breach starts' },
  { value: 60, label: '1 h after breach starts (night)' },
]

/**
 * Graham (1999) loss-of-life estimate. Always shown as a range with its method,
 * its assumptions and its caveats — never as a bare number.
 */
export default function LifeLossPanel({ runId }: { runId: string | null }) {
  const [warningMin, setWarningMin] = useState(0)
  const [showCaveats, setShowCaveats] = useState(false)
  const q = useLifeLoss(runId, warningMin, 'vague')

  if (!runId) return null
  const d = q.data
  return (
    <Panel title="Loss-of-Life Estimate" subtitle="Graham (1999), USBR DSO-99-06">
      <label className="mb-2 block">
        <span className="mb-0.5 block text-[11px] font-medium text-slate-600">
          Warning issued (assumption)
        </span>
        <select
          className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-xs"
          value={warningMin}
          onChange={(e) => setWarningMin(Number(e.target.value))}
          aria-label="Warning issued"
        >
          {WARNING_CHOICES.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
      </label>

      {q.isLoading && <Skeleton className="h-16" />}
      {q.isError && (
        <p className="text-[11px] text-rose-800">{(q.error as Error).message}</p>
      )}
      {d && !d.computed && (
        <p className="text-[11px] text-slate-600" data-testid="life-loss-not-computed">
          — Not computed: {d.reason ?? d.notes?.join(' ')}
        </p>
      )}
      {d && d.computed && (
        <div className="space-y-1.5 text-[11px] text-slate-700">
          <p>
            <span className="text-lg font-semibold text-slate-900" data-testid="life-loss-range">
              {formatNumber(d.range[0], 0)}–{formatNumber(d.range[1], 0)}
            </span>{' '}
            people (suggested value {formatNumber(d.estimate, 0)})
          </p>
          <p>
            Of {formatNumber(d.population_at_risk, 0)} modelled residents in the flooded area.
            Severity by Graham&rsquo;s 10 ft rule; flood-severity understanding assumed{' '}
            <em>vague</em>.
          </p>
          {d.par_without_a_rate ? (
            <p className="text-amber-800">
              {formatNumber(d.par_without_a_rate, 0)} people fall in a category Graham gives no
              rate for; they are not in the range.
            </p>
          ) : null}
          <button
            type="button"
            className="text-sky-700 hover:underline"
            onClick={() => setShowCaveats((v) => !v)}
          >
            {showCaveats ? 'Hide' : 'Show'} method and caveats
          </button>
          {showCaveats && (
            <div className="space-y-1 rounded bg-slate-50 p-2 text-[10px] leading-relaxed">
              <p>{d.citation}</p>
              <ul className="list-disc pl-4">
                {d.caveats.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Panel>
  )
}
