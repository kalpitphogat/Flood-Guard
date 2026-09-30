import { useState } from 'react'
import { useProvenance } from '../api/hooks'
import { Panel, Skeleton } from './Value'

/**
 * What produced this run's numbers. Every row is read from the run's own files
 * and names the field it came from; the labels above it are derived from the
 * same fields, so assumptions and caveats cannot be left out of the view.
 */
export default function ProvenancePanel({ runId }: { runId: string | null }) {
  const q = useProvenance(runId)
  const [open, setOpen] = useState(false)
  if (!runId) return null
  const cautions = q.data?.labels.filter((l) => l.level === 'caution') ?? []

  return (
    <Panel
      title="Provenance"
      subtitle="where every number came from"
      action={
        <button type="button" className="text-[11px] text-sky-700 hover:underline"
                onClick={() => setOpen((v) => !v)}>
          {open ? 'Hide' : 'Show all'}
        </button>
      }
    >
      {q.isLoading && <Skeleton className="h-16" />}
      {q.isError && <p className="text-[11px] text-slate-600">{(q.error as Error).message}</p>}
      {q.data && (
        <div className="space-y-2 text-[11px]">
          <ul className="space-y-1" data-testid="provenance-labels">
            {q.data.labels.map((l) => (
              <li key={l.text + l.source}
                  className={l.level === 'caution' ? 'text-amber-900' : 'text-slate-600'}
                  title={l.source}>
                {l.level === 'caution' ? '⚠ ' : 'ⓘ '}
                {l.text}
              </li>
            ))}
          </ul>
          {!open && (
            <p className="text-[10px] text-slate-500">
              {cautions.length} caution(s). Show all for every value with its source field.
            </p>
          )}
          {open &&
            q.data.sections.map((s) => (
              <div key={s.title}>
                <h4 className="mt-2 font-semibold text-slate-700">{s.title}</h4>
                <table className="w-full text-left">
                  <tbody>
                    {s.rows.map((r) => (
                      <tr key={r.label} className="border-b border-slate-100 align-top">
                        <td className="py-0.5 pr-2 text-slate-500">{r.label}</td>
                        <td className="py-0.5 pr-2 text-slate-800">{String(r.value)}</td>
                        <td className="py-0.5 font-mono text-[9px] text-slate-400">{r.source}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
        </div>
      )}
    </Panel>
  )
}
