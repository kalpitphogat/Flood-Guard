import * as maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef, useState } from 'react'
import { useLegend } from '../api/hooks'
import type { MapLayer, ScenarioSummary, TownAlert, TownResult } from '../types/api'

/**
 * The inundation map.
 *
 * Every result layer is served as XYZ raster tiles from the backend rather
 * than as GeoJSON features. That is the spec's large-data requirement: a 30 m
 * inundation polygon set over a 120 km reach is tens of megabytes of
 * geometry, and the browser should never see it. Tiles keep the payload
 * constant regardless of how large the simulated domain is.
 *
 * When a frame index is given, the tiles are the solver's stored depth field
 * at that time, so the raster itself animates — not just the town markers.
 *
 * The basemap uses a keyless raster source so the map works at a venue with no
 * accounts configured.
 */

export const BASEMAP_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution: '© OpenStreetMap contributors',
      maxzoom: 19,
    },
    satellite: {
      type: 'raster',
      tiles: [
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      ],
      tileSize: 256,
      attribution: 'Imagery © Esri, Maxar, Earthstar Geographics',
      maxzoom: 18,
    },
  },
  layers: [
    { id: 'osm', type: 'raster', source: 'osm' },
    { id: 'satellite', type: 'raster', source: 'satellite', layout: { visibility: 'none' } },
  ],
}

export const LAYER_TITLES: Record<MapLayer, string> = {
  depth: 'Maximum water depth',
  velocity: 'Maximum velocity',
  arrival: 'Flood arrival time',
  hazard: 'Hazard class (AIDR 7)',
  difference: 'Depth difference between engines',
}

export function tileUrl(
  runId: string,
  layer: MapLayer,
  engine?: string | null,
  frame?: number | null,
): string {
  const params = new URLSearchParams({ layer })
  if (engine) params.set('engine', engine)
  if (frame !== null && frame !== undefined) params.set('frame', String(frame))
  return `${window.location.origin}/api/results/${runId}/tiles/{z}/{x}/{y}.png?${params}`
}

export interface MapViewProps {
  runId: string | null
  scenario: ScenarioSummary | null
  towns: TownResult[]
  layer?: MapLayer
  engine?: string | null
  /** Index of a stored solver frame; null shows the maximum over the run. */
  frame?: number | null
  /** Simulated time in minutes for the town markers; null = whole run. */
  timeMinutes?: number | null
  aoiUploadId?: string | null
  /** Towns with a computed nearest safe ground; drawn as town → safe-point lines. */
  safeGround?: TownAlert[]
  className?: string
}

export default function MapView({
  runId,
  scenario,
  towns,
  layer = 'depth',
  engine = null,
  frame = null,
  timeMinutes = null,
  aoiUploadId = null,
  safeGround = [],
  className = '',
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const markersRef = useRef<maplibregl.Marker[]>([])
  const [ready, setReady] = useState(false)
  const [satellite, setSatellite] = useState(false)

  // --- create the map once ---
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BASEMAP_STYLE,
      center: [78.4, 30.2],
      zoom: 8,
      attributionControl: { compact: true },
    })
    map.addControl(new maplibregl.NavigationControl({ showCompass: true }), 'top-right')
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: 'metric' }), 'bottom-left')
    map.addControl(new maplibregl.FullscreenControl(), 'top-right')
    map.on('load', () => setReady(true))
    mapRef.current = map

    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return
    map.setLayoutProperty('satellite', 'visibility', satellite ? 'visible' : 'none')
  }, [ready, satellite])

  // --- fly to the scenario ---
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready || !scenario) return
    map.flyTo({ center: [scenario.lon, scenario.lat], zoom: 9, duration: 900 })
  }, [ready, scenario])

  // --- result tiles ---
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return

    if (map.getLayer('result')) map.removeLayer('result')
    if (map.getSource('result')) map.removeSource('result')
    if (!runId) return

    map.addSource('result', {
      type: 'raster',
      tiles: [tileUrl(runId, frame !== null ? 'depth' : layer, engine, frame)],
      tileSize: 256,
      minzoom: 5,
      maxzoom: 14,
    })
    map.addLayer(
      {
        id: 'result',
        type: 'raster',
        source: 'result',
        paint: {
          'raster-opacity': 0.8,
          'raster-resampling': 'nearest',
          'raster-fade-duration': 0,
        },
      },
      map.getLayer('aoi-line') ? 'aoi-line' : undefined,
    )
  }, [ready, runId, layer, engine, frame])

  // --- AOI overlay ---
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return
    for (const id of ['aoi-line', 'aoi-fill']) if (map.getLayer(id)) map.removeLayer(id)
    if (map.getSource('aoi')) map.removeSource('aoi')
    if (!aoiUploadId) return
    map.addSource('aoi', { type: 'geojson', data: `/api/uploads/${aoiUploadId}/geojson` })
    map.addLayer({
      id: 'aoi-fill',
      type: 'fill',
      source: 'aoi',
      paint: { 'fill-color': '#7c3aed', 'fill-opacity': 0.06 },
    })
    map.addLayer({
      id: 'aoi-line',
      type: 'line',
      source: 'aoi',
      paint: { 'line-color': '#7c3aed', 'line-width': 2, 'line-dasharray': [2, 1] },
    })
  }, [ready, aoiUploadId])

  // --- nearest safe ground: a dashed line from each town to its safe point ---
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return
    for (const id of ['safe-line', 'safe-point']) if (map.getLayer(id)) map.removeLayer(id)
    if (map.getSource('safe')) map.removeSource('safe')
    const withTarget = safeGround.filter((t) => t.safe_ground)
    if (!withTarget.length) return
    map.addSource('safe', {
      type: 'geojson',
      data: {
        type: 'FeatureCollection',
        features: withTarget.flatMap((t) => [
          {
            type: 'Feature' as const,
            properties: { town: t.name },
            geometry: {
              type: 'LineString' as const,
              coordinates: [
                [t.lon, t.lat],
                [t.safe_ground!.lon, t.safe_ground!.lat],
              ],
            },
          },
          {
            type: 'Feature' as const,
            properties: { town: t.name },
            geometry: {
              type: 'Point' as const,
              coordinates: [t.safe_ground!.lon, t.safe_ground!.lat],
            },
          },
        ]),
      },
    })
    map.addLayer({
      id: 'safe-line',
      type: 'line',
      source: 'safe',
      filter: ['==', ['geometry-type'], 'LineString'],
      paint: { 'line-color': '#15803d', 'line-width': 2, 'line-dasharray': [1.5, 1] },
    })
    map.addLayer({
      id: 'safe-point',
      type: 'circle',
      source: 'safe',
      filter: ['==', ['geometry-type'], 'Point'],
      paint: {
        'circle-radius': 6,
        'circle-color': '#22c55e',
        'circle-stroke-color': '#14532d',
        'circle-stroke-width': 2,
      },
    })
  }, [ready, safeGround])

  // --- dam and town markers ---
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return

    markersRef.current.forEach((m) => m.remove())
    markersRef.current = []

    if (scenario) {
      const el = document.createElement('div')
      el.innerHTML = `
        <div style="display:flex;flex-direction:column;align-items:center">
          <div style="width:0;height:0;border-left:8px solid transparent;
               border-right:8px solid transparent;border-bottom:14px solid #c62828"></div>
          <div style="background:#c62828;color:#fff;font:600 10px sans-serif;
               padding:1px 4px;border-radius:2px;white-space:nowrap;margin-top:1px">
            ${escapeHtml(scenario.dam)}
          </div>
        </div>`
      markersRef.current.push(
        new maplibregl.Marker({ element: el, anchor: 'bottom' })
          .setLngLat([scenario.lon, scenario.lat])
          .addTo(map),
      )
    }

    towns.forEach((town) => {
      const isWet =
        town.arrival_min !== null &&
        (timeMinutes === null || town.arrival_min <= timeMinutes)
      const el = document.createElement('div')
      el.innerHTML = `
        <div style="display:flex;flex-direction:column;align-items:center">
          <div style="width:10px;height:10px;border-radius:50%;
               background:${isWet ? '#1565c0' : '#fff'};
               border:2px solid ${isWet ? '#0d47a1' : '#607d8b'};
               ${isWet ? 'box-shadow:0 0 0 4px rgba(21,101,192,.25)' : ''}"></div>
          <div style="background:rgba(255,255,255,.92);color:#263238;
               font:500 10px sans-serif;padding:0 3px;border-radius:2px;
               white-space:nowrap;margin-top:1px">${escapeHtml(town.name)}</div>
        </div>`
      el.title =
        town.arrival_min !== null
          ? `${town.name}: arrives at ${Math.round(town.arrival_min)} min, depth ${
              town.max_depth_m?.toFixed(1) ?? '—'
            } m`
          : `${town.name}: not flooded in this run`
      markersRef.current.push(
        new maplibregl.Marker({ element: el, anchor: 'top' })
          .setLngLat([town.lon, town.lat])
          .addTo(map),
      )
    })
  }, [ready, scenario, towns, timeMinutes])

  return (
    <div className={`relative ${className}`}>
      <div ref={containerRef} className="h-full w-full" />
      <button
        type="button"
        onClick={() => setSatellite((v) => !v)}
        className="absolute left-2 top-2 rounded border border-slate-300 bg-white/95 px-2 py-1
                   text-[10px] font-medium text-slate-700 shadow hover:bg-white"
      >
        {satellite ? 'Street map' : 'Satellite'}
      </button>
      {runId && <Legend runId={runId} layer={frame !== null ? 'depth' : layer} />}
      {!runId && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <div className="rounded bg-white/90 px-4 py-2 text-xs text-slate-600 shadow">
            No simulation loaded. Run one, or switch on Demo Mode to load a completed run.
          </div>
        </div>
      )}
    </div>
  )
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)
}

/** Legend read from the backend, which draws the tiles with the same bins. */
export function Legend({ runId, layer }: { runId: string; layer: MapLayer }) {
  const legend = useLegend(runId, layer)
  if (!legend.data) return null
  const bins = [...legend.data.bins].reverse()
  return (
    <div className="absolute bottom-6 right-2 max-w-[210px] rounded border border-slate-200 bg-white/95 p-2 text-[10px] shadow">
      <div className="mb-1 font-semibold uppercase tracking-wide text-slate-600">
        {LAYER_TITLES[layer]}
      </div>
      {bins.map((bin) => (
        <div key={bin.label} className="flex items-start gap-1.5 leading-tight">
          <span
            className="mt-0.5 inline-block h-2.5 w-4 shrink-0 rounded-sm border border-slate-200"
            style={{ background: bin.colour }}
          />
          <span className="text-slate-700" title={bin.label}>
            {layer === 'hazard' ? bin.label.split(':')[0] : bin.label}
          </span>
        </div>
      ))}
    </div>
  )
}
