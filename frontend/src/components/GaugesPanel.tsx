import { useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useGauges } from '../api/hooks'
import type { GaugePoint } from '../types/api'
import { NOT_COMPUTED, Panel, Skeleton, formatMinutes, formatNumber } from './Value'

const AXIS = { fontSize: 10, fill: '#64748b' }

function flags(g: GaugePoint | null): string[] {
  if (!g) return []
  const out: string[] = []
  if (!g.in_domain) out.push('outside the computed area')
  if (g.rising_at_end) out.push('still rising when the run ends')
  if (g.near_domain_edge) out.push('near the domain edge')
  if (g.note) out.push(g.note)
  return out
}

/**
 * Depth over time at each named town and at the river beside it, read from
 * the solver's stored frames. The town point and the channel point are shown
 * separately because a town's published coordinate can be kilometres from the
 * river and stay dry while the valley floor floods.
 */
export default function GaugesPanel({ runId }: { runId: string | null }) {
  const q = useGauges(runId)
  const [selected, setSelected] = useState<string | null>(null)
  if (!runId) return null

  const gauges = q.data?.gauges ?? []
  const current = gauges.find((g) => g.name === selected) ?? gauges[0] ?? null
  const rows =
    current && q.data
      ? q.data.times_min.map((t, i) => ({
          minutes: t,
          channel: current.channel?.series_m?.[i] ?? null,
          town: current.town.series_m?.[i] ?? null,
        }))
      : []

  return (
    <Panel title="Town Gauges" subtitle="depth over time, from the stored solver frames">
      {q.isLoading && <Skeleton className="h-32" />}
      {q.isError && <p className="text-[11px] text-slate-600">{(q.error as Error).message}</p>}
      {q.data && (
        <div className="space-y-2">
          <table className="w-full text-left text-[11px]">
            <thead>
              <tr className="border-b border-slate-200 text-slate-500">
                <th className="py-1 pr-1">Town</th>
                <th className="py-1 pr-1">km</th>
                <th className="py-1 pr-1">River: arrival</th>
                <th className="py-1 pr-1">River: peak</th>
                <th className="py-1">Town point</th>
              </tr>
            </thead>
            <tbody>
              {gauges.map((g) => (
                <tr
                  key={g.name}
                  onClick={() => setSelected(g.name)}
                  className={`cursor-pointer border-b border-slate-100 ${
                    current?.name === g.name ? 'bg-sky-50' : 'hover:bg-slate-50'
                  }`}
                >
                  <td className="py-1 pr-1 font-medium text-slate-800">{g.name}</td>
                  <td className="py-1 pr-1">{formatNumber(g.chainage_km, 0)}</td>
                  <td className="py-1 pr-1">{formatMinutes(g.channel?.arrival_min ?? null)}</td>
                  <td className="py-1 pr-1">
                    {g.channel?.max_depth_m != null ? `${formatNumber(g.channel.max_depth_m, 1)} m` : NOT_COMPUTED}
                  </td>
                  <td className="py-1">
                    {g.town.in_domain
                      ? g.town.max_depth_m != null && g.town.max_depth_m >= 0.3
                        ? `${formatNumber(g.town.max_depth_m, 1)} m`
                        : 'dry'
                      : NOT_COMPUTED}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {current && rows.length > 0 && (
            <>
              <p className="text-[11px] text-slate-600">
                <strong>{current.name}</strong>
                {current.town_to_channel_km != null &&
                  ` — town point ${formatNumber(current.town_to_channel_km, 1)} km from the river`}
                {current.channel?.hazard_label && `, river hazard ${current.channel.hazard_label}`}
              </p>
              <ResponsiveContainer width="100%" height={160}>
                <LineChart data={rows} margin={{ top: 4, right: 8, bottom: 16, left: 0 }}>
                  <CartesianGrid stroke="#e2e8f0" strokeDasharray="2 3" />
                  <XAxis
                    dataKey="minutes"
                    tick={AXIS}
                    tickFormatter={(v) => `${Math.round(Number(v))}`}
                    label={{ value: 'minutes after breach start', position: 'insideBottom', offset: -8, ...AXIS }}
                  />
                  <YAxis tick={AXIS} label={{ value: 'depth (m)', angle: -90, position: 'insideLeft', ...AXIS }} />
                  <Tooltip contentStyle={{ fontSize: 11 }} />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  {current.channel && (
                    <Line dataKey="channel" name="river at the town" stroke="#0369a1" dot={false} connectNulls={false} />
                  )}
                  <Line dataKey="town" name="town point" stroke="#b45309" dot={false} connectNulls={false} />
                </LineChart>
              </ResponsiveContainer>
              {[...flags(current.channel), ...flags(current.town)].length > 0 && (
                <ul className="list-disc pl-4 text-[10px] text-amber-800" data-testid="gauge-flags">
                  {[...new Set([...flags(current.channel), ...flags(current.town)])].map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                </ul>
              )}
            </>
          )}
          <p className="text-[10px] leading-relaxed text-slate-500">
            {q.data.notes.join(' ')}
          </p>
        </div>
      )}
    </Panel>
  )
}
