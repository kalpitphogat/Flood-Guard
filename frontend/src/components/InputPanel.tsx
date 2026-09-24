import { useEffect, useMemo, useState } from 'react'
import { useBreachPreview, useDams, useEngines, useRivers, useScenarios } from '../api/hooks'
import type { ScenarioSummary, ScenarioType, SimulationRequest } from '../types/api'
import UploadPanel, { type UploadSelection } from './UploadPanel'
import { EngineBadge, Panel, Skeleton, formatNumber } from './Value'

const SCENARIO_TYPES: Array<{ value: ScenarioType; label: string; note?: string }> = [
  { value: 'complete_dam_break', label: 'Complete Dam Break' },
  { value: 'partial_breach', label: 'Partial Breach' },
  { value: 'piping_failure', label: 'Piping Failure' },
  { value: 'overtopping', label: 'Overtopping' },
  { value: 'controlled_release', label: 'Controlled Release' },
  {
    value: 'landslide_dam_breach',
    label: 'Landslide Dam Breach',
    note: 'Natural blockage failure, as at Rishi Ganga in February 2021.',
  },
]

/** Engines offered in the model picker, in display order, with plain-language names. */
const ENGINE_CHOICES: Array<{ id: string; label: string }> = [
  { id: 'swe_fv', label: 'FloodGuard-SWE — 2D finite volume (Delft3D-class)' },
  { id: 'sph_swe', label: 'FloodGuard-SPH — smoothed particle hydrodynamics' },
  { id: 'delft3d', label: 'Delft3D Flexible Mesh (external)' },
  { id: 'sph_pysph', label: 'PySPH 3D WCSPH (external)' },
  { id: 'anuga', label: 'ANUGA (independent cross-check)' },
]

export interface InputPanelProps {
  onRun: (request: SimulationRequest) => void
  running: boolean
  onReset: () => void
  /** Reports what is selected, so the map can fly there before any run. */
  onSelectionChange?: (summary: ScenarioSummary | null) => void
  uploads: UploadSelection
  onUploadsChange: (next: UploadSelection) => void
}

export default function InputPanel({
  onRun,
  running,
  onReset,
  onSelectionChange,
  uploads,
  onUploadsChange,
}: InputPanelProps) {
  const scenarios = useScenarios()
  const rivers = useRivers()
  const engines = useEngines()

  const [scenarioId, setScenarioId] = useState<string>('')
  const [river, setRiver] = useState<string>('')
  const [scenarioType, setScenarioType] = useState<ScenarioType>('complete_dam_break')
  const [level, setLevel] = useState<string>('')
  const [width, setWidth] = useState<string>('')
  const [depth, setDepth] = useState<string>('')
  const [formation, setFormation] = useState<string>('')
  const [duration, setDuration] = useState<string>('')
  const [resolution, setResolution] = useState<string>('90')
  const [selectedEngines, setSelectedEngines] = useState<string[]>(['swe_fv', 'sph_swe'])
  const [showAdvanced, setShowAdvanced] = useState(false)
  // A bundled scenario, or any dam in the CWC NRLD catalog.
  const [source, setSource] = useState<'scenario' | 'dam'>('scenario')
  const [damId, setDamId] = useState<string>('')

  const dams = useDams(river || undefined)
  const dam = dams.data?.find((d) => d.id === damId) ?? null

  // Default to the first bundled scenario so the page is never empty.
  useEffect(() => {
    if (!scenarioId && scenarios.data?.length) {
      const first = scenarios.data.find((s) => s.valid)
      if (first) {
        setScenarioId(first.id)
        setRiver(first.river)
        setDuration(String(first.duration_hours))
      }
    }
  }, [scenarios.data, scenarioId])

  const active = scenarios.data?.find((s) => s.id === scenarioId) ?? null

  useEffect(() => {
    if (!onSelectionChange) return
    if (source === 'scenario') {
      onSelectionChange(active)
    } else if (dam) {
      onSelectionChange({
        id: `adhoc_${dam.id}`,
        name: `${dam.name} dam break`,
        description: '',
        dam: dam.name,
        river: dam.river,
        state: dam.state,
        lon: dam.lon,
        lat: dam.lat,
        scenario_type: scenarioType,
        resolution_m: Number(resolution) || 90,
        duration_hours: Number(duration) || 6,
        reach_length_km: 0,
        towns: [],
        valid: true,
      })
    } else {
      onSelectionChange(null)
    }
    // onSelectionChange is a setter from the parent; identity is stable enough.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, active, dam, scenarioType, resolution, duration])

  // A catalog dam has no published FRL in the NRLD transcription, so the
  // level must be typed; it is never guessed.
  const needsLevel = source === 'dam' && !dam?.frl_m && !level

  const request: SimulationRequest | null = useMemo(() => {
    if (source === 'scenario' && !scenarioId) return null
    if (source === 'dam' && !damId) return null
    return {
      ...(source === 'scenario' ? { scenario_id: scenarioId } : { dam_id: damId }),
      dem_upload_id: uploads.dem,
      hydrograph_upload_id: uploads.hydrograph,
      scenario_type: scenarioType,
      reservoir_level_m: level ? Number(level) : null,
      breach: {
        width_m: width ? Number(width) : null,
        depth_m: depth ? Number(depth) : null,
        formation_time_min: formation ? Number(formation) : null,
      },
      engines: selectedEngines,
      resolution_m: resolution ? Number(resolution) : null,
      duration_hours: duration ? Number(duration) : null,
    }
  }, [
    source, scenarioId, damId, uploads.dem, uploads.hydrograph, scenarioType, level, width,
    depth, formation, selectedEngines, resolution, duration,
  ])

  // Ghost hints: what the empirical models predict, live, before running.
  const preview = useBreachPreview(
    request && !needsLevel ? { ...request, breach: {} } : null,
  )
  const predicted = preview.data?.used
  const spread = preview.data?.spread

  const toggleEngine = (id: string) =>
    setSelectedEngines((prev) =>
      prev.includes(id) ? prev.filter((e) => e !== id) : [...prev, id],
    )

  const validationError =
    preview.isError && request
      ? (preview.error as Error)?.message ?? 'this configuration is not valid'
      : null

  return (
    <div className="space-y-3">
      <Panel title="Select River & Dam">
        {scenarios.isLoading ? (
          <Skeleton className="h-16" />
        ) : (
          <div className="space-y-2">
            <div className="flex rounded border border-slate-300 p-0.5 text-[11px]">
              {(
                [
                  ['scenario', 'Bundled scenario'],
                  ['dam', 'Any catalog dam'],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setSource(value)}
                  className={`flex-1 rounded py-0.5 ${
                    source === value ? 'bg-sky-700 font-medium text-white' : 'text-slate-600'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>

            {source === 'scenario' && (
            <Field label="Scenario">
              <select
                className={selectClass}
                value={scenarioId}
                onChange={(e) => {
                  const next = scenarios.data?.find((s) => s.id === e.target.value)
                  setScenarioId(e.target.value)
                  if (next) {
                    setRiver(next.river)
                    setDuration(String(next.duration_hours))
                  }
                }}
              >
                {scenarios.data?.filter((s) => s.valid).map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </Field>
            )}

            <Field label="River">
              <select
                className={selectClass}
                value={river}
                onChange={(e) => setRiver(e.target.value)}
              >
                <option value="">All rivers</option>
                {rivers.data?.map((r) => (
                  <option key={r.name} value={r.name}>
                    {r.name} ({r.dam_count})
                  </option>
                ))}
              </select>
            </Field>

            {source === 'dam' && (
              <Field label="Dam in catalog (CWC NRLD-2019)">
                <select
                  className={selectClass}
                  value={damId}
                  onChange={(e) => setDamId(e.target.value)}
                >
                  <option value="">Choose a dam…</option>
                  {dams.data?.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name} — {d.state}
                    </option>
                  ))}
                </select>
              </Field>
            )}

            {source === 'dam' && dam && (
              <div className="space-y-1 text-[11px] leading-relaxed text-slate-500">
                <p>
                  {dam.name} on the <strong>{dam.river}</strong>, {dam.state}. Height{' '}
                  {formatNumber(dam.structural_height_m, 1)} m, gross storage{' '}
                  {formatNumber(dam.gross_storage_mcm, 0)} MCM.
                </p>
                <p>
                  The DEM for this dam is fetched automatically on the first run (a few
                  minutes); later runs reuse the cache.
                </p>
                {!dam.frl_m && (
                  <p className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-amber-900">
                    The NRLD tables publish no full reservoir level for this dam. Enter the
                    reservoir water level below — FloodGuard will not guess it.
                  </p>
                )}
              </div>
            )}

            {source === 'scenario' && active && (
              <p className="text-[11px] leading-relaxed text-slate-500">
                {active.dam} on the <strong>{active.river}</strong>, {active.state}.{' '}
                {active.reach_length_km} km reach, towns: {active.towns.join(', ')}.
              </p>
            )}
          </div>
        )}
      </Panel>

      <Panel
        title="Scenario Configuration"
        subtitle="Empirical predictions shown as hints; your values override them"
      >
        <div className="space-y-2">
          <Field label="Scenario Type">
            <select
              className={selectClass}
              value={scenarioType}
              onChange={(e) => setScenarioType(e.target.value as ScenarioType)}
            >
              {SCENARIO_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </Field>
          {SCENARIO_TYPES.find((t) => t.value === scenarioType)?.note && (
            <p className="text-[10px] text-slate-500">
              {SCENARIO_TYPES.find((t) => t.value === scenarioType)!.note}
            </p>
          )}

          <NumberField
            label="Reservoir Water Level"
            unit="m MSL"
            value={level}
            onChange={setLevel}
            placeholder="scenario default"
          />
          <NumberField
            label="Breach Width"
            unit="m"
            value={width}
            onChange={setWidth}
            placeholder={predicted ? `${Math.round(predicted.width_m)} predicted` : 'predicted'}
            hint={
              predicted
                ? `${predicted.model.split(' ')[0]} predicts ${Math.round(predicted.width_m)} m`
                : undefined
            }
          />
          <NumberField
            label="Breach Depth"
            unit="m"
            value={depth}
            onChange={setDepth}
            placeholder={predicted ? `${Math.round(predicted.depth_m)} predicted` : 'predicted'}
          />
          <NumberField
            label="Breach Formation Time"
            unit="min"
            value={formation}
            onChange={setFormation}
            placeholder={
              predicted ? `${Math.round(predicted.formation_time_min)} predicted` : 'predicted'
            }
          />
          <NumberField
            label="Simulation Duration"
            unit="hours"
            value={duration}
            onChange={setDuration}
          />

          {spread && spread.width_m.spread_ratio > 2 && (
            <div className="rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-[10px] leading-relaxed text-amber-900">
              The three empirical breach models disagree by a factor of{' '}
              <strong>{spread.width_m.spread_ratio.toFixed(1)}</strong> on width
              ({Math.round(spread.width_m.min)}–{Math.round(spread.width_m.max)} m).
              Breach geometry, not the solver, is the dominant uncertainty in this result.
            </div>
          )}

          {validationError && (
            <div className="rounded border border-rose-200 bg-rose-50 px-2 py-1.5 text-[10px] text-rose-900">
              {validationError}
            </div>
          )}
        </div>
      </Panel>

      <Panel title="Select Models" subtitle="Availability probed on this machine">
        <div className="space-y-1.5">
          {engines.isLoading && <Skeleton className="h-12" />}
          {ENGINE_CHOICES.map((choice) => engines.data?.engines.find((e) => e.id === choice.id))
            .filter((e): e is NonNullable<typeof e> => !!e)
            .map((engine) => (
              <label
                key={engine.id}
                className="flex cursor-pointer items-start gap-2 rounded px-1 py-1 hover:bg-slate-50"
              >
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={selectedEngines.includes(engine.id)}
                  onChange={() => toggleEngine(engine.id)}
                />
                <span className="flex-1">
                  <span className="block text-xs font-medium text-slate-800">
                    {ENGINE_CHOICES.find((c) => c.id === engine.id)?.label ?? engine.id}
                  </span>
                  <span className="mt-0.5 block">
                    <EngineBadge
                      displayName={engine.available ? engine.display_name : `→ ${engine.substitute_id ?? 'unavailable'}`}
                      isRealSolver={engine.is_real_solver}
                      substituted={!engine.available}
                      detail={engine.detail}
                    />
                  </span>
                </span>
              </label>
            ))}
          {engines.data && (
            <p className="pt-1 text-[10px] leading-relaxed text-slate-500">
              {engines.data.honesty_statement}
            </p>
          )}
        </div>
      </Panel>

      <UploadPanel selection={uploads} onChange={onUploadsChange} />

      {needsLevel && (
        <p className="text-[10px] text-amber-800">Enter a reservoir water level to run this dam.</p>
      )}
      {selectedEngines.length >= 2 && (
        <p className="text-[10px] leading-relaxed text-slate-500">
          {selectedEngines.length} engines selected: they run one after another on the same
          grid, and the Comparison View fills itself from their results.
        </p>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          disabled={!request || running || selectedEngines.length === 0 || needsLevel}
          onClick={() => request && onRun(request)}
          className="flex-1 rounded bg-sky-700 px-3 py-2 text-sm font-medium text-white
                     transition-colors hover:bg-sky-800 disabled:cursor-not-allowed
                     disabled:bg-slate-300"
        >
          {running ? 'Running…' : 'Run Simulation'}
        </button>
        <button
          type="button"
          onClick={onReset}
          className="rounded border border-slate-300 px-3 py-2 text-sm text-slate-700
                     hover:bg-slate-50"
        >
          Reset
        </button>
      </div>

      <Panel
        title="Additional Options"
        action={
          <button
            type="button"
            className="text-[11px] text-sky-700 hover:underline"
            onClick={() => setShowAdvanced((v) => !v)}
          >
            {showAdvanced ? 'Hide' : 'Show'}
          </button>
        }
      >
        {showAdvanced ? (
          <div className="space-y-2">
            <NumberField
              label="Grid resolution"
              unit="m"
              value={resolution}
              onChange={setResolution}
              hint="Cost scales as roughly 1/res³. Peak depths are genuinely resolution-sensitive."
            />
            <p className="text-[10px] leading-relaxed text-slate-500">
              A coarse cell averages the channel together with its banks and under-predicts
              the peak, so this is exposed rather than fixed. Every output records the
              resolution it was computed at. 30 m is the publication setting; 90–120 m is
              interactive.
            </p>
          </div>
        ) : (
          <p className="text-[11px] text-slate-500">
            Grid resolution, Manning&rsquo;s n overrides, CFL and output interval.
          </p>
        )}
      </Panel>
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

function NumberField({
  label,
  unit,
  value,
  onChange,
  placeholder,
  hint,
}: {
  label: string
  unit: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  hint?: string
}) {
  return (
    <label className="block">
      <span className="mb-0.5 flex items-baseline justify-between">
        <span className="text-[11px] font-medium text-slate-600">{label}</span>
        <span className="text-[10px] text-slate-400">{unit}</span>
      </span>
      <input
        type="number"
        inputMode="decimal"
        className={selectClass}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
      {hint && <span className="mt-0.5 block text-[10px] text-slate-400">{hint}</span>}
    </label>
  )
}
