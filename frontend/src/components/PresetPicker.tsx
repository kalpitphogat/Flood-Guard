import { useEffect, useMemo, useState } from 'react'
import type { PresetCatalog, PresetEntry } from '../types/api'
import { formatNumber } from './Value'

export interface PresetPickerProps {
  catalog: PresetCatalog
  running: boolean
  onRun: (preset: PresetEntry) => void
  /** Reports the selected dam so the map can fly there before any run. */
  onDamChange?: (scenarioId: string) => void
}

/**
 * Three dropdowns over the precomputed library: dam, failure type, reservoir
 * level. Only combinations whose stored run exists can be run; the rest say
 * why they are not offered instead of silently disappearing.
 */
export default function PresetPicker({ catalog, running, onRun, onDamChange }: PresetPickerProps) {
  const [damId, setDamId] = useState(catalog.dams[0]?.scenario_id ?? '')
  const [type, setType] = useState('complete_dam_break')
  const [level, setLevel] = useState('frl')
  const [resolution, setResolution] = useState<number>(catalog.resolution_m)
  const resolutions = catalog.resolutions?.length ? catalog.resolutions : [catalog.resolution_m]

  useEffect(() => {
    if (damId) onDamChange?.(damId)
    // onDamChange is a setter from the parent; identity is stable enough.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [damId])

  const dam = catalog.dams.find((d) => d.scenario_id === damId) ?? null
  const byKey = useMemo(() => {
    const m = new Map<string, PresetEntry>()
    for (const p of catalog.presets)
      m.set(`${p.scenario_id}|${p.scenario_type}|${p.level}|${p.resolution_m ?? catalog.resolution_m}`, p)
    return m
  }, [catalog.presets, catalog.resolution_m])
  const find = (t: string, l: string, r: number = resolution) =>
    byKey.get(`${damId}|${t}|${l}|${r}`) ?? null
  const resolutionUsable = (r: number) =>
    dam?.levels.some((l) => find(type, l.level, r)?.available) ?? false

  const typeUsable = (t: string) => dam?.levels.some((l) => find(t, l.level)?.available) ?? false
  const selected = find(type, level)

  return (
    <div className="space-y-2">
      <Field label="Dam">
        <select className={selectClass} value={damId} onChange={(e) => setDamId(e.target.value)}
                aria-label="Dam">
          {catalog.dams.map((d) => (
            <option key={d.scenario_id} value={d.scenario_id}>
              {d.name}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Failure type">
        <select className={selectClass} value={type} onChange={(e) => setType(e.target.value)}
                aria-label="Failure type">
          {Object.entries(catalog.failure_types).map(([value, label]) => (
            <option key={value} value={value} disabled={!typeUsable(value)}>
              {label}
              {typeUsable(value) ? '' : ' — not precomputed yet'}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Reservoir level">
        <select className={selectClass} value={level} onChange={(e) => setLevel(e.target.value)}
                aria-label="Reservoir level">
          {dam?.levels.map((l) => {
            const entry = find(type, l.level)
            return (
              <option key={l.level} value={l.level} disabled={!entry?.available}>
                {l.label} — {formatNumber(l.level_m, 2)} m
                {entry?.available ? '' : ' — not precomputed yet'}
              </option>
            )
          })}
        </select>
      </Field>

      <Field label="Grid resolution">
        <select className={selectClass} value={resolution}
                onChange={(e) => setResolution(Number(e.target.value))} aria-label="Grid resolution">
          {resolutions.map((r) => (
            <option key={r} value={r} disabled={!resolutionUsable(r)}>
              {formatNumber(r, 0)} m{r === catalog.resolution_m ? ' (default)' : ' (finer)'}
              {resolutionUsable(r) ? '' : ' — not precomputed yet'}
            </option>
          ))}
        </select>
      </Field>

      {selected && !selected.available && selected.reason && (
        <p className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-[10px] leading-relaxed text-amber-900"
           role="note">
          {selected.reason}
        </p>
      )}
      {selected?.available && (
        <p className="text-[10px] leading-relaxed text-slate-500">
          Precomputed on {selected.completed_utc?.slice(0, 10) ?? '—'} with the full pipeline at{' '}
          {formatNumber(selected.resolution_m ?? catalog.resolution_m, 0)} m, {formatNumber(dam?.duration_hours ?? null, 0)} h
          simulated
          {selected.wall_seconds !== null
            ? ` (took ${formatNumber(selected.wall_seconds / 60, 1)} min to compute)`
            : ''}
          . Loads instantly — no solver runs now.
        </p>
      )}

      <button
        type="button"
        disabled={!selected?.available || running}
        onClick={() => selected && onRun(selected)}
        className="w-full rounded bg-sky-700 px-3 py-2 text-sm font-medium text-white
                   transition-colors hover:bg-sky-800 disabled:cursor-not-allowed
                   disabled:bg-slate-300"
      >
        Show precomputed result
      </button>
    </div>
  )
}

const selectClass =
  'w-full rounded border border-slate-300 bg-white px-2 py-1 text-xs text-slate-800 ' +
  'focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-0.5 block text-[11px] font-medium text-slate-600">{label}</span>
      {children}
    </label>
  )
}
