import { useRegistry } from '../api/hooks'
import { Panel, Skeleton } from './Value'

const TONE: Record<string, string> = {
  'presets ready': 'bg-emerald-100 text-emerald-900',
  'partly ready': 'bg-sky-100 text-sky-900',
  'inputs ready': 'bg-amber-100 text-amber-900',
  'not ready': 'bg-slate-200 text-slate-700',
}

/**
 * The dams this install can model, each with a readiness badge computed on the
 * server from files on this machine — and the reason, so every badge answers
 * "how do you know?".
 */
export default function RegistryPanel() {
  const q = useRegistry()
  return (
    <Panel title="Sites on this machine" subtitle="readiness computed from the files present">
      {q.isLoading && <Skeleton className="h-16" />}
      {q.isError && <p className="text-[11px] text-slate-600">{(q.error as Error).message}</p>}
      {q.data && (
        <div className="space-y-2">
          {q.data.sites.map((s) => (
            <div key={s.scenario_id} className="rounded border border-slate-200 p-2 text-[11px]">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-slate-800">{s.dam} — {s.river}</span>
                <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${TONE[s.tier] ?? ''}`}
                      data-testid="tier">
                  {s.tier}
                </span>
              </div>
              <p className="mt-0.5 text-slate-600">{s.tier_reason}</p>
              <ul className="mt-1 grid grid-cols-2 gap-x-2 text-[10px] text-slate-500">
                {Object.entries(s.resolutions).map(([res, v]) => (
                  <li key={res}>
                    {res} m: {v.presets_stored}/{v.presets_defined} presets ·{' '}
                    {v.terrain.ok ? 'terrain ✓' : 'no terrain'}
                  </li>
                ))}
                <li>population raster: {s.population_raster ? 'yes' : 'no'}</li>
                <li>OSM layers: {s.osm_layers.length || 'none'}</li>
              </ul>
            </div>
          ))}
          <p className="text-[10px] text-slate-500">{q.data.note}</p>
        </div>
      )}
    </Panel>
  )
}
