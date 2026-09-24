import { Deck } from '@deck.gl/core'
import type { MapViewState } from '@deck.gl/core'
import { TerrainLayer } from '@deck.gl/geo-layers'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useScene3D } from '../api/hooks'
import { formatNumber } from './Value'

/**
 * 3D view: the conditioned bed the solver ran on, with the computed water
 * surface draped over it.
 *
 * Both surfaces come from the run's own rasters (bed.tif and the depth field),
 * reprojected to lon/lat by the backend and Terrarium-encoded, so the water
 * sits exactly where the solver put it. Dry pixels are sent 50 m below the bed,
 * where the terrain hides them — no depth is invented to make the scene look
 * continuous. Vertical exaggeration is a display control and is labelled.
 */

const TERRARIUM = { rScaler: 256, gScaler: 1, bScaler: 1 / 256, offset: -32768 }

export interface Scene3DProps {
  runId: string
  frame: number | null
  engine?: string | null
  className?: string
}

export default function Scene3D({ runId, frame, engine = null, className = '' }: Scene3DProps) {
  const meta = useScene3D(runId)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const deckRef = useRef<Deck | null>(null)
  const [exaggeration, setExaggeration] = useState(2)
  const [showWater, setShowWater] = useState(true)

  const initialView: MapViewState | null = useMemo(() => {
    if (!meta.data) return null
    const [w, s, e, n] = meta.data.bounds
    const span = Math.max(e - w, n - s)
    return {
      longitude: (w + e) / 2,
      latitude: (s + n) / 2,
      zoom: Math.max(6, Math.log2(360 / span) - 0.3),
      pitch: 55,
      bearing: -20,
      maxPitch: 85,
    }
  }, [meta.data])

  useEffect(() => {
    if (!containerRef.current || !initialView || deckRef.current) return
    deckRef.current = new Deck({
      parent: containerRef.current,
      initialViewState: initialView,
      controller: true,
      layers: [],
      style: { position: 'absolute', inset: '0' } as unknown as Partial<CSSStyleDeclaration>,
    })
    return () => {
      deckRef.current?.finalize()
      deckRef.current = null
    }
  }, [initialView])

  useEffect(() => {
    const deck = deckRef.current
    if (!deck || !meta.data) return
    const k = exaggeration
    const decoder = {
      rScaler: TERRARIUM.rScaler * k,
      gScaler: TERRARIUM.gScaler * k,
      bScaler: TERRARIUM.bScaler * k,
      offset: TERRARIUM.offset * k,
    }
    const frameQuery = new URLSearchParams()
    if (frame !== null) frameQuery.set('frame', String(frame))
    if (engine) frameQuery.set('engine', engine)
    const q = frameQuery.toString() ? `?${frameQuery}` : ''
    const base = `/api/results/${runId}/3d`

    const layers = [
      new TerrainLayer({
        id: 'terrain',
        bounds: meta.data.bounds,
        elevationData: `${base}/terrain.png`,
        texture: `${base}/terrain-texture.png`,
        elevationDecoder: decoder,
        meshMaxError: 4,
        color: [255, 255, 255],
      }),
      showWater &&
        new TerrainLayer({
          id: `water-${frame ?? 'max'}-${engine ?? 'primary'}`,
          bounds: meta.data.bounds,
          elevationData: `${base}/water.png${q}`,
          texture: `${base}/water-texture.png${q}`,
          elevationDecoder: decoder,
          meshMaxError: 2,
          opacity: 0.9,
        }),
    ].filter(Boolean)
    deck.setProps({ layers })
  }, [meta.data, runId, frame, engine, exaggeration, showWater])

  if (meta.isError) {
    return (
      <div className={`flex items-center justify-center p-6 text-center ${className}`}>
        <p className="max-w-sm text-xs leading-relaxed text-slate-500">
          {(meta.error as Error).message}
        </p>
      </div>
    )
  }

  return (
    <div className={`relative bg-slate-900 ${className}`}>
      <div ref={containerRef} className="absolute inset-0" />
      {meta.isLoading && (
        <div className="absolute inset-0 flex items-center justify-center text-xs text-slate-300">
          Reprojecting terrain and water surface…
        </div>
      )}
      {meta.data && (
        <div className="absolute left-2 top-2 space-y-1 rounded bg-white/95 p-2 text-[10px] text-slate-700 shadow">
          <div className="font-semibold uppercase tracking-wide text-slate-600">3D scene</div>
          <label className="flex items-center gap-1.5">
            Vertical ×{exaggeration}
            <input
              type="range"
              min={1}
              max={5}
              step={0.5}
              value={exaggeration}
              onChange={(e) => setExaggeration(Number(e.target.value))}
            />
          </label>
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={showWater}
              onChange={(e) => setShowWater(e.target.checked)}
            />
            Water surface {frame === null ? '(maximum)' : '(this frame)'}
          </label>
          <div className="text-slate-500">
            Bed {formatNumber(meta.data.bed_min_m, 0)}–{formatNumber(meta.data.bed_max_m, 0)} m
            MSL · peak depth {formatNumber(meta.data.max_depth_m, 1)} m
          </div>
          <div className="text-slate-400">Drag to pan · right-drag to tilt</div>
        </div>
      )}
    </div>
  )
}
