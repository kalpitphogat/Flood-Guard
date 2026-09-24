/** TanStack Query hooks. One place where every endpoint is called. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api } from './client'
import type {
  Comparison,
  CrossSectionResponse,
  DamSummary,
  EngineHealth,
  HydrographResponse,
  ImpactResponse,
  JobCreated,
  JobState,
  ResultSummary,
  RiverSummary,
  ScenarioSummary,
  SimulationRequest,
  TownResult,
  BreachComparison,
  AoiStats,
  FramesResponse,
  LegendBin,
  MapLayer,
  RunListing,
  Scene3DMeta,
  ShareCreated,
  ShareResolved,
  UploadKind,
  UploadMeta,
} from '../types/api'

export function useEngines() {
  return useQuery({
    queryKey: ['engines'],
    queryFn: () => api<EngineHealth>('/api/health/engines'),
    staleTime: 60_000,
  })
}

export function useRivers() {
  return useQuery({
    queryKey: ['rivers'],
    queryFn: () => api<RiverSummary[]>('/api/rivers'),
    staleTime: Infinity,
  })
}

export function useDams(river?: string) {
  return useQuery({
    queryKey: ['dams', river ?? 'all'],
    queryFn: () =>
      api<DamSummary[]>(`/api/dams${river ? `?river=${encodeURIComponent(river)}` : ''}`),
    staleTime: Infinity,
  })
}

export function useScenarios() {
  return useQuery({
    queryKey: ['scenarios'],
    queryFn: () => api<ScenarioSummary[]>('/api/scenarios'),
    staleTime: Infinity,
  })
}

/** Breach predictions for the ghost hints, without running a simulation. */
export function useBreachPreview(request: SimulationRequest | null) {
  return useQuery({
    queryKey: ['breach-preview', JSON.stringify(request)],
    queryFn: () =>
      api<BreachComparison>('/api/scenarios/validate', {
        method: 'POST',
        body: JSON.stringify(request),
      }),
    enabled: !!request,
    retry: false,
  })
}

export function useSubmitSimulation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (request: SimulationRequest) =>
      api<JobCreated>('/api/simulate', {
        method: 'POST',
        body: JSON.stringify(request),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  })
}

export function useJob(jobId: string | null) {
  return useQuery({
    queryKey: ['job', jobId],
    queryFn: () => api<JobState>(`/api/jobs/${jobId}`),
    enabled: !!jobId,
    // The WebSocket carries live progress; this poll is the fallback for when
    // the socket cannot connect, and the safety net for a missed close frame.
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'running' || status === 'queued' ? 4000 : false
    },
  })
}

/**
 * Live job progress over the WebSocket, falling back silently to the poll in
 * `useJob` when the socket cannot be established.
 */
export function useJobSocket(jobId: string | null) {
  const [state, setState] = useState<Partial<JobState> | null>(null)
  const [connected, setConnected] = useState(false)
  const socketRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!jobId) {
      setState(null)
      return
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${window.location.host}/ws/jobs/${jobId}`

    let closed = false
    let ws: WebSocket
    try {
      ws = new WebSocket(url)
    } catch {
      return
    }
    socketRef.current = ws

    ws.onopen = () => !closed && setConnected(true)
    ws.onclose = () => !closed && setConnected(false)
    ws.onerror = () => !closed && setConnected(false)
    ws.onmessage = (event) => {
      if (closed) return
      try {
        const payload = JSON.parse(event.data)
        if (payload.type === 'ping') return
        setState((prev) => ({ ...(prev ?? {}), ...payload }))
      } catch {
        /* a malformed frame must not break the panel */
      }
    }

    return () => {
      closed = true
      ws.close()
      socketRef.current = null
    }
  }, [jobId])

  return { live: state, connected }
}

export function useResultSummary(runId: string | null) {
  return useQuery({
    queryKey: ['result', runId, 'summary'],
    queryFn: () => api<ResultSummary>(`/api/results/${runId}/summary`),
    enabled: !!runId,
    retry: false,
  })
}

export function useTowns(runId: string | null) {
  return useQuery({
    queryKey: ['result', runId, 'towns'],
    queryFn: () => api<TownResult[]>(`/api/results/${runId}/towns`),
    enabled: !!runId,
    retry: false,
  })
}

export function useComparison(runId: string | null) {
  return useQuery({
    queryKey: ['result', runId, 'comparison'],
    queryFn: () => api<Comparison>(`/api/results/${runId}/comparison`),
    enabled: !!runId,
    retry: false,
  })
}

export function useImpact(runId: string | null) {
  return useQuery({
    queryKey: ['result', runId, 'impact'],
    queryFn: () => api<ImpactResponse>(`/api/results/${runId}/impact`),
    enabled: !!runId,
    retry: false,
  })
}

export function useHydrographs(runId: string | null) {
  return useQuery({
    queryKey: ['result', runId, 'hydrographs'],
    queryFn: () => api<HydrographResponse>(`/api/results/${runId}/hydrographs`),
    enabled: !!runId,
    retry: false,
  })
}

export function useCrossSection(runId: string | null, location: string | null) {
  return useQuery({
    queryKey: ['result', runId, 'cross-section', location],
    queryFn: () =>
      api<CrossSectionResponse>(
        `/api/results/${runId}/cross-section?location=${encodeURIComponent(location!)}`,
      ),
    enabled: !!runId && !!location,
    retry: false,
  })
}

// --- runs, frames, sharing, uploads, 3D, AOI ------------------------------------

export function useRuns() {
  return useQuery({
    queryKey: ['runs'],
    queryFn: () => api<RunListing[]>('/api/runs'),
    staleTime: 15_000,
  })
}

export function useFrames(runId: string | null) {
  return useQuery({
    queryKey: ['result', runId, 'frames'],
    queryFn: () => api<FramesResponse>(`/api/results/${runId}/frames`),
    enabled: !!runId,
    retry: false,
  })
}

export function useLegend(runId: string | null, layer: MapLayer) {
  return useQuery({
    queryKey: ['result', runId, 'legend', layer],
    queryFn: () => api<{ layer: string; bins: LegendBin[] }>(
      `/api/results/${runId}/legend?layer=${layer}`,
    ),
    enabled: !!runId,
    staleTime: Infinity,
    retry: false,
  })
}

export function useTownsByEngine(runId: string | null) {
  return useQuery({
    queryKey: ['result', runId, 'towns-by-engine'],
    queryFn: () => api<Record<string, TownResult[]>>(`/api/results/${runId}/towns-by-engine`),
    enabled: !!runId,
    retry: false,
  })
}

export function useCreateShare() {
  return useMutation({
    mutationFn: ({ runId, view }: { runId: string; view: Record<string, unknown> }) =>
      api<ShareCreated>(`/api/results/${runId}/share`, {
        method: 'POST',
        body: JSON.stringify({ view }),
      }),
  })
}

export function useResolveShare(code: string | undefined) {
  return useQuery({
    queryKey: ['share', code],
    queryFn: () => api<ShareResolved>(`/api/share/${code}`),
    enabled: !!code,
    retry: false,
  })
}

export function useUploads(kind?: UploadKind) {
  return useQuery({
    queryKey: ['uploads', kind ?? 'all'],
    queryFn: () => api<UploadMeta[]>(`/api/uploads${kind ? `?kind=${kind}` : ''}`),
  })
}

/** Multipart upload. The JSON helper cannot be used: it forces a JSON content type. */
export function useUploadFile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ kind, file }: { kind: UploadKind; file: File }) => {
      const body = new FormData()
      body.append('file', file)
      const base = import.meta.env.VITE_API_BASE ?? ''
      const res = await fetch(`${base}/api/uploads/${kind}`, { method: 'POST', body })
      const payload = await res.json().catch(() => ({}))
      if (!res.ok) {
        const detail = payload?.detail
        const issues: string[] = Array.isArray(detail?.issues) ? detail.issues : []
        const message =
          typeof detail === 'string' ? detail : detail?.message ?? res.statusText
        throw Object.assign(new Error(message), { issues })
      }
      return payload as UploadMeta
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['uploads'] }),
  })
}

export function useScene3D(runId: string | null) {
  return useQuery({
    queryKey: ['result', runId, '3d-meta'],
    queryFn: () => api<Scene3DMeta>(`/api/results/${runId}/3d/meta`),
    enabled: !!runId,
    retry: false,
  })
}

export function useAoiStats(runId: string | null, uploadId: string | null) {
  return useQuery({
    queryKey: ['result', runId, 'aoi', uploadId],
    queryFn: () => api<AoiStats>(`/api/results/${runId}/aoi-stats?upload_id=${uploadId}`),
    enabled: !!runId && !!uploadId,
    retry: false,
  })
}
