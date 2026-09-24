import * as maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef, useState } from 'react'
import type { MapLayer, ScenarioSummary } from '../types/api'
import { BASEMAP_STYLE, Legend, tileUrl } from './MapView'

/**
 * Side-by-side swipe between two engines' results for the same run.
 *
 * Two MapLibre maps are stacked and kept in lock-step; the right one is
 * clipped at the divider. Both layers are the engines' own rasters from disk —
 * nothing here blends, resamples or averages them — so what differs on either
 * side of the line is exactly what the solvers computed differently.
 */
export interface SwipeMapProps {
  runId: string
  scenario: ScenarioSummary | null
  left: { id: string; label: string }
  right: { id: string; label: string }
  layer?: MapLayer
  className?: string
}

export default function SwipeMap({
  runId,
  scenario,
  left,
  right,
  layer = 'depth',
  className = '',
}: SwipeMapProps) {
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const leftRef = useRef<HTMLDivElement | null>(null)
  const rightRef = useRef<HTMLDivElement | null>(null)
  const maps = useRef<{ a?: maplibregl.Map; b?: maplibregl.Map }>({})
  const [ready, setReady] = useState(0)
  const [split, setSplit] = useState(0.5)
  const dragging = useRef(false)

  useEffect(() => {
    if (!leftRef.current || !rightRef.current) return
    const center: [number, number] = scenario ? [scenario.lon, scenario.lat] : [78.4, 30.2]
    const make = (container: HTMLDivElement, withControls: boolean) => {
      const map = new maplibregl.Map({
        container,
        style: BASEMAP_STYLE,
        center,
        zoom: 9,
        attributionControl: withControls ? { compact: true } : false,
      })
      if (withControls) {
        map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
      }
      map.on('load', () => setReady((n) => n + 1))
      return map
    }
    const a = make(leftRef.current, false)
    const b = make(rightRef.current, true)
    maps.current = { a, b }

    // Lock-step: whichever map the user moves drives the other.
    let syncing = false
    const sync = (from: maplibregl.Map, to: maplibregl.Map) => () => {
      if (syncing) return
      syncing = true
      to.jumpTo({
        center: from.getCenter(),
        zoom: from.getZoom(),
        bearing: from.getBearing(),
        pitch: from.getPitch(),
      })
      syncing = false
    }
    a.on('move', sync(a, b))
    b.on('move', sync(b, a))

    return () => {
      a.remove()
      b.remove()
      maps.current = {}
    }
    // The maps are created once per scenario; layers are swapped below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenario?.id])

  useEffect(() => {
    if (ready < 2) return
    const pairs: Array<[maplibregl.Map | undefined, string]> = [
      [maps.current.a, left.id],
      [maps.current.b, right.id],
    ]
    for (const [map, engine] of pairs) {
      if (!map) continue
      if (map.getLayer('result')) map.removeLayer('result')
      if (map.getSource('result')) map.removeSource('result')
      map.addSource('result', {
        type: 'raster',
        tiles: [tileUrl(runId, layer, engine)],
        tileSize: 256,
        minzoom: 5,
        maxzoom: 14,
      })
      map.addLayer({
        id: 'result',
        type: 'raster',
        source: 'result',
        paint: { 'raster-opacity': 0.8, 'raster-resampling': 'nearest' },
      })
    }
  }, [ready, runId, layer, left.id, right.id])

  // Keep the canvases sized when the container changes (tab switches).
  useEffect(() => {
    const t = window.setTimeout(() => {
      maps.current.a?.resize()
      maps.current.b?.resize()
    }, 50)
    return () => window.clearTimeout(t)
  }, [ready])

  const onPointer = (clientX: number) => {
    const rect = wrapRef.current?.getBoundingClientRect()
    if (!rect) return
    setSplit(Math.min(0.98, Math.max(0.02, (clientX - rect.left) / rect.width)))
  }

  return (
    <div
      ref={wrapRef}
      className={`relative select-none overflow-hidden ${className}`}
      onPointerMove={(e) => dragging.current && onPointer(e.clientX)}
      onPointerUp={() => (dragging.current = false)}
      onPointerLeave={() => (dragging.current = false)}
    >
      <div ref={leftRef} className="absolute inset-0" />
      <div
        ref={rightRef}
        className="absolute inset-0"
        style={{ clipPath: `inset(0 0 0 ${split * 100}%)` }}
      />
      <div
        role="slider"
        aria-label="Swipe between engines"
        aria-valuenow={Math.round(split * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'ArrowLeft') setSplit((s) => Math.max(0.02, s - 0.05))
          if (e.key === 'ArrowRight') setSplit((s) => Math.min(0.98, s + 0.05))
        }}
        onPointerDown={(e) => {
          dragging.current = true
          ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
        }}
        onPointerMove={(e) => dragging.current && onPointer(e.clientX)}
        className="absolute inset-y-0 z-10 w-1 -translate-x-1/2 cursor-ew-resize bg-white shadow-[0_0_0_1px_rgba(15,23,42,.4)]"
        style={{ left: `${split * 100}%` }}
      >
        <div className="absolute top-1/2 left-1/2 flex h-8 w-8 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-slate-300 bg-white text-xs text-slate-600 shadow">
          ⇆
        </div>
      </div>
      <div className="pointer-events-none absolute left-2 top-2 z-10 rounded bg-slate-900/80 px-2 py-1 text-[10px] font-medium text-white">
        ◀ {left.label}
      </div>
      <div className="pointer-events-none absolute right-12 top-2 z-10 rounded bg-slate-900/80 px-2 py-1 text-[10px] font-medium text-white">
        {right.label} ▶
      </div>
      <Legend runId={runId} layer={layer} />
    </div>
  )
}
