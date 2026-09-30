import { Suspense, lazy, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  useCreateShare,
  useFrames,
  useJob,
  useJobSocket,
  useResultSummary,
  useRuns,
  useScenarios,
  useSubmitSimulation,
  useTowns,
  useWarning,
} from '../api/hooks'
import { BreachEnsembleChart, CrossSectionChart, HydrographChart } from '../components/Charts'
import InputPanel from '../components/InputPanel'
import GaugesPanel from '../components/GaugesPanel'
import LifeLossPanel from '../components/LifeLossPanel'
import ProvenancePanel from '../components/ProvenancePanel'
import SensitivityPanel from '../components/SensitivityPanel'
import PlaybackSpeed, { frameIntervalMs } from '../components/PlaybackSpeed'
import StopButton from '../components/StopButton'
import RunModeBadge from '../components/RunModeBadge'
import MapView, { LAYER_TITLES } from '../components/MapView'
import {
  AoiPanel,
  ComparisonTable,
  ExportPanel,
  ImpactPanel,
  ResultsPanel,
  TownTable,
  TownsByEngineTable,
} from '../components/ResultsPanel'
import SwipeMap from '../components/SwipeMap'
import type { UploadSelection } from '../components/UploadPanel'
import WarningPanel from '../components/WarningPanel'
import { Panel, formatMinutes, formatNumber } from '../components/Value'
import type { MapLayer, ScenarioSummary, SimulationRequest } from '../types/api'

type MapTab = 'inundation' | 'comparison' | '3d'

// deck.gl is large and only the 3D tab needs it.
const Scene3D = lazy(() => import('../components/Scene3D'))

const ENGINE_SHORT: Record<string, string> = {
  swe_fv: 'FloodGuard-SWE (finite volume)',
  sph_swe: 'FloodGuard-SPH (particles)',
}

export default function Simulation() {
  const scenarios = useScenarios()
  const submit = useSubmitSimulation()
  const runs = useRuns()
  const share = useCreateShare()
  const [params, setParams] = useSearchParams()

  const [jobId, setJobId] = useState<string | null>(null)
  const [runId, setRunId] = useState<string | null>(params.get('run'))
  const [selection, setSelection] = useState<ScenarioSummary | null>(null)
  const [engineIndex, setEngineIndex] = useState(0)
  const [tab, setTab] = useState<MapTab>((params.get('tab') as MapTab) || 'inundation')
  const [layer, setLayer] = useState<MapLayer>((params.get('layer') as MapLayer) || 'depth')
  const [mapEngine, setMapEngine] = useState<string | null>(params.get('engine'))
  const [frame, setFrame] = useState<number | null>(
    params.get('frame') !== null ? Number(params.get('frame')) : null,
  )
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [sectionLocation, setSectionLocation] = useState<string | null>(null)
  const [demoMode, setDemoMode] = useState<boolean>(params.get('demo') === '1')
  const [uploads, setUploads] = useState<UploadSelection>({ dem: null, hydrograph: null, aoi: null })
  const [shareUrl, setShareUrl] = useState<string | null>(null)

  const job = useJob(jobId)
  const { live, connected } = useJobSocket(jobId)
  const towns = useTowns(runId)
  const summary = useResultSummary(runId)
  const frames = useFrames(runId)
  const warning = useWarning(runId)

  // The scenario shown on the map: the loaded run's scenario when there is
  // one, otherwise whatever is selected in the input panel.
  const runScenarioId = summary.data?.scenario_id ?? null
  const scenario = useMemo(() => {
    const fromRun = scenarios.data?.find((s) => s.id === runScenarioId)
    return fromRun ?? selection
  }, [scenarios.data, runScenarioId, selection])

  // Keep the URL in step with the view, so a copied address reopens it.
  useEffect(() => {
    const next = new URLSearchParams()
    if (runId) next.set('run', runId)
    if (tab !== 'inundation') next.set('tab', tab)
    if (layer !== 'depth') next.set('layer', layer)
    if (mapEngine) next.set('engine', mapEngine)
    if (frame !== null) next.set('frame', String(frame))
    if (demoMode) next.set('demo', '1')
    setParams(next, { replace: true })
  }, [runId, tab, layer, mapEngine, frame, demoMode, setParams])

  // The run id is the job id: the pipeline writes into data/runs/<job_id>.
  useEffect(() => {
    if (job.data?.status === 'succeeded' && jobId) {
      setRunId(jobId)
      runs.refetch()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.data?.status, jobId])

  // Demo Mode: load the newest completed run instantly, no solver involved.
  useEffect(() => {
    if (demoMode && !runId && runs.data?.length) {
      const best = [...runs.data].sort((a, b) => b.engine_count - a.engine_count)[0]
      setRunId(best.run_id)
    }
  }, [demoMode, runId, runs.data])

  useEffect(() => {
    if (!sectionLocation && scenario?.towns.length) setSectionLocation(scenario.towns[0])
  }, [scenario, sectionLocation])

  const status = (live?.status as string) ?? job.data?.status ?? null
  const running = status === 'queued' || status === 'running'
  const fraction = live?.fraction ?? job.data?.fraction ?? 0
  const phase = live?.phase ?? job.data?.phase ?? ''
  const message = live?.message ?? job.data?.message ?? ''
  const eta = job.data?.eta_seconds ?? null

  const engines = summary.data?.engines.filter((e) => e.max_depth_m !== null || e.flooded_area_km2 !== null) ?? []
  const primaryEngine = engines[0]?.engine_id ?? null
  const frameEngine = mapEngine ?? primaryEngine
  const frameTimes = (frameEngine && frames.data?.engines[frameEngine]) || []
  const frameMinutes = frame !== null && frameTimes[frame] !== undefined ? frameTimes[frame] / 60 : null

  // --- animation: step through the solver's stored frames ---
  useEffect(() => {
    if (!playing || frameTimes.length === 0) return
    const id = window.setInterval(() => {
      setFrame((prev) => {
        const next = (prev ?? -1) + 1
        if (next >= frameTimes.length) {
          setPlaying(false)
          return frameTimes.length - 1
        }
        return next
      })
    }, frameIntervalMs(speed))
    return () => window.clearInterval(id)
  }, [playing, frameTimes.length, speed])

  const loadRun = (id: string | null) => {
    setRunId(id)
    setFrame(null)
    setPlaying(false)
    setMapEngine(null)
    setShareUrl(null)
    setEngineIndex(0)
  }

  const handleRun = (request: SimulationRequest) => {
    loadRun(null)
    setDemoMode(false)
    submit.mutate(request, {
      onSuccess: (data) => {
        // A precomputed preset needs no job socket: its run is already on disk.
        if (data.mode === 'precomputed' && data.run_id) {
          setJobId(null)
          loadRun(data.run_id)
          runs.refetch()
        } else {
          setJobId(data.job_id)
        }
      },
    })
  }

  const handleReset = () => {
    setJobId(null)
    loadRun(null)
    setDemoMode(false)
  }

  const handleShare = () => {
    if (!runId) return
    const view: Record<string, unknown> = { layer, tab }
    if (mapEngine) view.engine = mapEngine
    if (frame !== null) view.frame = frame
    share.mutate(
      { runId, view },
      {
        onSuccess: (data) => {
          const url = `${window.location.origin}${data.path}`
          setShareUrl(url)
          navigator.clipboard?.writeText(url).catch(() => {})
        },
      },
    )
  }

  const twoEngines = engines.length >= 2
  const layers: MapLayer[] = ['depth', 'velocity', 'arrival', 'hazard', ...(twoEngines ? (['difference'] as MapLayer[]) : [])]

  return (
    <div className="mx-auto max-w-[1600px] px-3 py-3">
      {/* ---------------- toolbar ---------------- */}
      <div className="mb-3 flex flex-wrap items-center gap-2 rounded border border-slate-200 bg-white px-3 py-2">
        <label className="flex cursor-pointer items-center gap-2 text-xs font-medium text-slate-700">
          <span
            role="switch"
            aria-checked={demoMode}
            tabIndex={0}
            onClick={() => {
              setDemoMode((v) => !v)
              if (demoMode) loadRun(null)
            }}
            onKeyDown={(e) => e.key === 'Enter' && setDemoMode((v) => !v)}
            className={`relative inline-block h-4 w-7 rounded-full transition-colors ${
              demoMode ? 'bg-emerald-600' : 'bg-slate-300'
            }`}
          >
            <span
              className={`absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all ${
                demoMode ? 'left-3.5' : 'left-0.5'
              }`}
            />
          </span>
          Demo Mode
        </label>
        {demoMode && (
          <select
            className="rounded border border-slate-300 bg-white px-2 py-1 text-xs"
            value={runId ?? ''}
            onChange={(e) => loadRun(e.target.value || null)}
            aria-label="Precomputed run"
          >
            {!runs.data?.length && <option value="">No completed runs on this machine</option>}
            {runs.data?.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {r.scenario_id} · {r.resolution_m ? `${Math.round(r.resolution_m)} m` : '— m'} ·{' '}
                {r.engines.filter((e) => e.ok).map((e) => e.id).join(' + ')} ·{' '}
                {r.completed_utc.slice(0, 16).replace('T', ' ')}
              </option>
            ))}
          </select>
        )}
        <span className="text-[11px] text-slate-500">
          {demoMode
            ? 'Loads a completed run from disk instantly — no solver runs, and nothing is precomputed that a CLI run could not reproduce.'
            : 'Configure a scenario on the left and run it, or switch on Demo Mode.'}
        </span>
        <div className="ml-auto flex items-center gap-2">
          {shareUrl && (
            <input
              readOnly
              value={shareUrl}
              onFocus={(e) => e.target.select()}
              className="w-56 rounded border border-emerald-300 bg-emerald-50 px-2 py-1 font-mono text-[11px] text-emerald-900"
              aria-label="Share link"
            />
          )}
          <button
            type="button"
            disabled={!runId || share.isPending}
            onClick={handleShare}
            className="rounded bg-slate-800 px-3 py-1 text-xs font-medium text-white hover:bg-slate-900 disabled:bg-slate-300"
          >
            {shareUrl ? 'Copied ✓' : 'Share link'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-3">
        {/* ---------------- left: inputs ---------------- */}
        <div className="col-span-12 space-y-3 lg:col-span-3">
          <InputPanel
            onRun={handleRun}
            running={running}
            onReset={handleReset}
            onSelectionChange={setSelection}
            uploads={uploads}
            onUploadsChange={setUploads}
          />

          {jobId && (
            <Panel
              title="Run Progress"
              action={
                <span
                  className={`text-[10px] ${connected ? 'text-emerald-600' : 'text-slate-400'}`}
                  title={
                    connected
                      ? 'live over WebSocket'
                      : 'WebSocket unavailable; falling back to polling'
                  }
                >
                  {connected ? '● live' : '○ polling'}
                </span>
              }
            >
              <div className="space-y-1.5">
                <div className="h-1.5 w-full overflow-hidden rounded bg-slate-200">
                  <div
                    className="h-full bg-sky-600 transition-all"
                    style={{ width: `${Math.round(fraction * 100)}%` }}
                  />
                </div>
                <div className="flex items-baseline justify-between text-[11px]">
                  <span className="font-medium text-slate-700">
                    {phase || status} — {Math.round(fraction * 100)}%
                  </span>
                  {eta !== null && running && (
                    <span className="text-slate-500">~{formatMinutes(eta / 60)} left</span>
                  )}
                </div>
                {message && (
                  <p className="truncate font-mono text-[10px] text-slate-500" title={message}>
                    {message}
                  </p>
                )}
                {status === 'failed' && (
                  <pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded bg-rose-50 p-1.5 text-[10px] text-rose-900">
                    {job.data?.error}
                  </pre>
                )}
                {running && (
                  <StopButton jobId={jobId} />
                )}
                {status === 'cancelled' && (
                  <p className="text-[10px] text-slate-500" data-testid="stopped-note">
                    Stopped. The run's process was ended and its partial output discarded —
                    nothing from it is shown as a result.
                  </p>
                )}
                {status === 'interrupted' && (
                  <p className="text-[10px] text-amber-800">
                    Interrupted: the server restarted and this run's worker process was no
                    longer running. Start it again.
                  </p>
                )}
              </div>
            </Panel>
          )}
        </div>

        {/* ---------------- centre: map ---------------- */}
        <div className="col-span-12 space-y-3 lg:col-span-6">
          {runId && summary.data && (
            <div className="flex items-center gap-2">
              <RunModeBadge summary={summary.data} />
              <span className="font-mono text-[10px] text-slate-400">{runId}</span>
            </div>
          )}
          {submit.isError && (
            <p className="rounded border border-rose-200 bg-rose-50 px-2 py-1 text-[11px] text-rose-900">
              {(submit.error as Error).message}
            </p>
          )}
          <section className="overflow-hidden rounded border border-slate-200 bg-white">
            <div className="flex flex-wrap items-center border-b border-slate-200">
              {(
                [
                  ['inundation', 'Flood Inundation Map'],
                  ['comparison', 'Comparison View'],
                  ['3d', '3D View'],
                ] as Array<[MapTab, string]>
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setTab(value)}
                  className={`px-3 py-1.5 text-xs transition-colors ${
                    tab === value
                      ? 'border-b-2 border-sky-700 font-medium text-sky-800'
                      : 'text-slate-500 hover:text-slate-700'
                  }`}
                >
                  {label}
                </button>
              ))}
              {tab !== '3d' && runId && (
                <div className="ml-auto flex items-center gap-1.5 px-2">
                  <select
                    value={layer}
                    onChange={(e) => {
                      setLayer(e.target.value as MapLayer)
                      setFrame(null)
                      setPlaying(false)
                    }}
                    className="rounded border border-slate-300 bg-white px-1.5 py-0.5 text-[11px]"
                    aria-label="Map layer"
                  >
                    {layers.map((l) => (
                      <option key={l} value={l}>
                        {LAYER_TITLES[l]}
                      </option>
                    ))}
                  </select>
                  {tab === 'inundation' && engines.length > 1 && layer !== 'difference' && (
                    <select
                      value={mapEngine ?? ''}
                      onChange={(e) => setMapEngine(e.target.value || null)}
                      className="rounded border border-slate-300 bg-white px-1.5 py-0.5 text-[11px]"
                      aria-label="Engine shown on the map"
                    >
                      <option value="">Primary engine</option>
                      {engines.map((e) => (
                        <option key={e.engine_id} value={e.engine_id}>
                          {ENGINE_SHORT[e.engine_id] ?? e.engine_display_name}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
              )}
            </div>

            {tab === 'inundation' && (
              <MapView
                runId={runId}
                scenario={scenario}
                towns={towns.data ?? []}
                layer={layer}
                engine={layer === 'difference' ? null : mapEngine}
                frame={frame}
                timeMinutes={frameMinutes}
                aoiUploadId={uploads.aoi}
                safeGround={warning.data?.towns ?? []}
                className="h-[460px]"
              />
            )}

            {tab === 'comparison' && (
              <div>
                {runId && twoEngines ? (
                  <SwipeMap
                    runId={runId}
                    scenario={scenario}
                    left={{ id: engines[0].engine_id, label: ENGINE_SHORT[engines[0].engine_id] ?? engines[0].engine_display_name }}
                    right={{ id: engines[1].engine_id, label: ENGINE_SHORT[engines[1].engine_id] ?? engines[1].engine_display_name }}
                    layer={layer === 'difference' ? 'depth' : layer}
                    className="h-[420px]"
                  />
                ) : (
                  <div className="flex h-[140px] items-center justify-center p-4 text-center text-xs text-slate-500">
                    {runId
                      ? 'This run has one engine result, so there is nothing to swipe between. Select two engines and run again.'
                      : 'No simulation loaded.'}
                  </div>
                )}
                <div className="p-3">
                  <ComparisonTable runId={runId} />
                  <TownsByEngineTable runId={runId} />
                </div>
              </div>
            )}

            {tab === '3d' &&
              (runId ? (
                <Suspense
                  fallback={
                    <div className="flex h-[460px] items-center justify-center text-xs text-slate-500">
                      Loading the 3D renderer…
                    </div>
                  }
                >
                  <Scene3D runId={runId} frame={frame} engine={mapEngine} className="h-[460px]" />
                </Suspense>
              ) : (
                <div className="flex h-[460px] items-center justify-center text-xs text-slate-500">
                  No simulation loaded.
                </div>
              ))}

            {tab !== 'comparison' && (
              <>
                <div className="flex items-center gap-2 border-t border-slate-100 px-3 py-2">
                  <button
                    type="button"
                    disabled={!runId || frameTimes.length === 0}
                    onClick={() => {
                      if (frame === null || frame >= frameTimes.length - 1) setFrame(0)
                      setPlaying((p) => !p)
                    }}
                    className="rounded bg-sky-700 px-2 py-1 text-[11px] text-white disabled:bg-slate-300"
                  >
                    {playing ? '❚❚ Pause' : '▶ Play'}
                  </button>
                  <input
                    type="range"
                    min={0}
                    max={Math.max(frameTimes.length - 1, 0)}
                    step={1}
                    disabled={!runId || frameTimes.length === 0}
                    value={frame ?? Math.max(frameTimes.length - 1, 0)}
                    onChange={(e) => {
                      setPlaying(false)
                      setFrame(Number(e.target.value))
                    }}
                    className="flex-1"
                    aria-label="Simulation time"
                  />
                  <PlaybackSpeed
                    speed={speed}
                    onChange={setSpeed}
                    disabled={!runId || frameTimes.length === 0}
                  />
                  <span className="w-28 text-right font-mono text-[11px] text-slate-600">
                    {frame === null ? 'maximum extent' : `t = ${formatMinutes(frameMinutes)}`}
                  </span>
                  <button
                    type="button"
                    disabled={!runId}
                    onClick={() => {
                      setPlaying(false)
                      setFrame(null)
                    }}
                    className="rounded border border-slate-300 px-2 py-1 text-[11px] text-slate-600 disabled:opacity-50"
                    title="Show the maximum over the whole simulation"
                  >
                    Max
                  </button>
                </div>
                <p className="border-t border-slate-100 px-3 py-1 text-[10px] leading-relaxed text-slate-500">
                  {runId && frameTimes.length > 0
                    ? `Each step is a depth field the solver stored during the run (${frameTimes.length} frames, every ${formatNumber(frameTimes.length > 1 ? (frameTimes[1] - frameTimes[0]) / 60 : null, 0)} min) — the raster itself animates. Town markers turn blue when the computed wave reaches them.`
                    : runId
                      ? frames.data?.note ?? ''
                      : 'Load a run to animate the flood.'}
                </p>
              </>
            )}
          </section>

          <HydrographChart runId={runId} />
          <GaugesPanel runId={runId} />
          <BreachEnsembleChart runId={runId} />
          <SensitivityPanel runId={runId} />
          <CrossSectionChart
            runId={runId}
            scenario={scenario}
            location={sectionLocation}
            onLocationChange={setSectionLocation}
          />
        </div>

        {/* ---------------- right: results ---------------- */}
        <div className="col-span-12 space-y-3 lg:col-span-3">
          <ResultsPanel runId={runId} engineIndex={engineIndex} onEngineChange={setEngineIndex} />
          <WarningPanel runId={runId} />
          <AoiPanel runId={runId} uploadId={uploads.aoi} />
          <ImpactPanel runId={runId} />
          <LifeLossPanel runId={runId} />
          <TownTable runId={runId} />
          <ExportPanel runId={runId} />
          <ProvenancePanel runId={runId} />
        </div>
      </div>
    </div>
  )
}
