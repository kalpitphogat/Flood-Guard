import { useSensitivity } from '../api/hooks'
import { Panel, Skeleton, formatNumber } from './Value'

/**
 * Tornado chart: each breach input moved alone across FloodGuard's own range
 * for it, and the peak breach outflow that results. The widest bar is the
 * input that matters most for this dam.
 */
export default function SensitivityPanel({ runId }: { runId: string | null }) {
  const q = useSensitivity(runId)
  if (!runId) return null
  const d = q.data
  const all = d ? d.factors.flatMap((f) => [f.low.peak_m3s, f.high.peak_m3s, d.base.peak_m3s]) : []
  const lo = Math.min(...all)
  const hi = Math.max(...all)
  const pct = (v: number) => ((v - lo) / Math.max(hi - lo, 1)) * 100

  return (
    <Panel title="What Matters Most" subtitle="breach outflow sensitivity, one input at a time">
      {q.isLoading && <Skeleton className="h-24" />}
      {q.isError && <p className="text-[11px] text-slate-600">{(q.error as Error).message}</p>}
      {d && (
        <div className="space-y-2 text-[11px]">
          <p className="text-slate-600">
            Peak outflow for this run: <strong>{formatNumber(d.base.peak_m3s, 0)} m³/s</strong>
          </p>
          {d.factors.map((f) => {
            const a = pct(Math.min(f.low.peak_m3s, f.high.peak_m3s))
            const b = pct(Math.max(f.low.peak_m3s, f.high.peak_m3s))
            return (
              <div key={f.factor} data-testid="tornado-row">
                <div className="flex justify-between text-slate-700">
                  <span>{f.factor}</span>
                  <span className="text-slate-500">
                    {formatNumber(f.low.value, 1)} → {formatNumber(f.high.value, 1)}
                  </span>
                </div>
                <div className="relative mt-0.5 h-3 rounded bg-slate-100" title={f.basis}>
                  <div className="absolute h-3 rounded bg-sky-600"
                       style={{ left: `${a}%`, width: `${Math.max(b - a, 0.5)}%` }} />
                  <div className="absolute h-3 w-0.5 bg-rose-600"
                       title="base case"
                       style={{ left: `${pct(d.base.peak_m3s)}%` }} />
                </div>
                <div className="flex justify-between text-[10px] text-slate-500">
                  <span>{formatNumber(f.low.peak_m3s, 0)} m³/s</span>
                  <span>{formatNumber(f.high.peak_m3s, 0)} m³/s</span>
                </div>
              </div>
            )
          })}
          <ul className="list-disc pl-4 text-[10px] text-slate-500">
            {d.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  )
}
