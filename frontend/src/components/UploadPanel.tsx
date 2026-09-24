import { useRef, useState } from 'react'
import { useUploadFile, useUploads } from '../api/hooks'
import type { UploadKind, UploadMeta } from '../types/api'
import { Panel, formatNumber } from './Value'

/**
 * "Upload Custom Data": bring your own DEM, outflow hydrograph or area of
 * interest.
 *
 * Every file is validated on the server before it can be used — CRS present,
 * units plausible, time strictly increasing — and a refused file comes back
 * with every reason listed. Nothing is repaired silently: no CRS is assumed,
 * no discharge unit is converted.
 */

export interface UploadSelection {
  dem: string | null
  hydrograph: string | null
  aoi: string | null
}

const KINDS: Array<{ kind: UploadKind; label: string; accept: string; help: string }> = [
  {
    kind: 'dem',
    label: 'DEM (GeoTIFF)',
    accept: '.tif,.tiff',
    help: 'Must embed its CRS. Replaces the fetched Copernicus DEM, e.g. with Bhuvan CartoDEM.',
  },
  {
    kind: 'hydrograph',
    label: 'Outflow hydrograph (CSV)',
    accept: '.csv,.txt',
    help: 'Columns time_s|time_min|time_hours and discharge_m3s. Replaces the breach model.',
  },
  {
    kind: 'aoi',
    label: 'Area of interest',
    accept: '.geojson,.json,.kml,.zip',
    help: 'GeoJSON, KML or zipped SHP polygon — a district or block. Flood stats inside it.',
  },
]

export default function UploadPanel({
  selection,
  onChange,
}: {
  selection: UploadSelection
  onChange: (next: UploadSelection) => void
}) {
  const [open, setOpen] = useState(false)
  const active = Object.values(selection).filter(Boolean).length

  return (
    <Panel
      title="Upload Custom Data"
      subtitle={active ? `${active} upload(s) in use` : 'Swap in your own inputs'}
      action={
        <button
          type="button"
          className="text-[11px] text-sky-700 hover:underline"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? 'Hide' : 'Show'}
        </button>
      }
    >
      {open ? (
        <div className="space-y-3">
          {KINDS.map((k) => (
            <UploadSlot
              key={k.kind}
              {...k}
              selected={selection[k.kind]}
              onSelect={(id) => onChange({ ...selection, [k.kind]: id })}
            />
          ))}
        </div>
      ) : (
        <p className="text-[11px] text-slate-500">
          DEM GeoTIFF, outflow hydrograph CSV, AOI polygon — validated for CRS, extent and units.
        </p>
      )}
    </Panel>
  )
}

function UploadSlot({
  kind,
  label,
  accept,
  help,
  selected,
  onSelect,
}: {
  kind: UploadKind
  label: string
  accept: string
  help: string
  selected: string | null
  onSelect: (id: string | null) => void
}) {
  const uploads = useUploads(kind)
  const upload = useUploadFile()
  const inputRef = useRef<HTMLInputElement | null>(null)
  const error = upload.error as (Error & { issues?: string[] }) | null
  const current = uploads.data?.find((u) => u.id === selected) ?? null

  return (
    <div className="rounded border border-slate-200 p-2">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[11px] font-medium text-slate-700">{label}</span>
        <button
          type="button"
          disabled={upload.isPending}
          onClick={() => inputRef.current?.click()}
          className="rounded border border-slate-300 px-2 py-0.5 text-[10px] text-slate-700
                     hover:bg-slate-50 disabled:opacity-50"
        >
          {upload.isPending ? 'Validating…' : 'Choose file'}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          className="hidden"
          aria-label={`Upload ${label}`}
          onChange={(e) => {
            const file = e.target.files?.[0]
            e.target.value = ''
            if (!file) return
            upload.mutate({ kind, file }, { onSuccess: (meta) => onSelect(meta.id) })
          }}
        />
      </div>
      <p className="mb-1 text-[10px] leading-snug text-slate-500">{help}</p>

      {error && (
        <div role="alert" className="rounded border border-rose-200 bg-rose-50 px-2 py-1 text-[10px] text-rose-900">
          <div className="font-medium">{error.message}</div>
          {error.issues?.map((issue) => (
            <div key={issue} className="mt-0.5">• {issue}</div>
          ))}
        </div>
      )}

      {(uploads.data?.length ?? 0) > 0 && (
        <select
          className="w-full rounded border border-slate-300 bg-white px-1.5 py-0.5 text-[11px]"
          value={selected ?? ''}
          onChange={(e) => onSelect(e.target.value || null)}
          aria-label={`Use a ${label} upload`}
        >
          <option value="">— not used —</option>
          {uploads.data!.map((u) => (
            <option key={u.id} value={u.id}>
              {u.original_filename} ({u.uploaded_utc.slice(0, 10)})
            </option>
          ))}
        </select>
      )}
      {current && <UploadSummary meta={current} />}
    </div>
  )
}

function UploadSummary({ meta }: { meta: UploadMeta }) {
  const facts: string[] = []
  if (meta.kind === 'dem') {
    facts.push(`${meta.crs}`, `${formatNumber(meta.resolution_m, 1)} m`)
    facts.push(
      `${formatNumber(meta.elevation_min_m, 0)}–${formatNumber(meta.elevation_max_m, 0)} m`,
    )
    if (meta.nodata_fraction !== undefined)
      facts.push(`${(meta.nodata_fraction * 100).toFixed(1)}% nodata`)
  }
  if (meta.kind === 'hydrograph') {
    facts.push(`peak ${formatNumber(meta.peak_discharge_m3s, 0)} m³/s`)
    facts.push(`at ${formatNumber(meta.time_to_peak_min, 0)} min`)
    facts.push(`${formatNumber(meta.volume_mcm, 1)} MCM`)
    facts.push(`${formatNumber(meta.duration_hours, 1)} h`)
  }
  if (meta.kind === 'aoi') {
    facts.push(`${meta.features} polygon(s)`, `${formatNumber(meta.area_km2, 1)} km²`)
  }
  return (
    <div className="mt-1 space-y-0.5 text-[10px]">
      <div className="text-emerald-700">✓ accepted · {facts.join(' · ')}</div>
      {meta.warnings.map((w) => (
        <div key={w} className="text-amber-700">⚠ {w}</div>
      ))}
      {meta.sha256 && (
        <div className="truncate font-mono text-slate-400" title={meta.sha256}>
          sha256 {meta.sha256.slice(0, 16)}…
        </div>
      )}
    </div>
  )
}
