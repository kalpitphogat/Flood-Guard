import { useState } from 'react'
import { useWarning } from '../api/hooks'
import type { AlertLevel, TownAlert } from '../types/api'
import { NOT_COMPUTED, Panel, Skeleton, formatMinutes, formatNumber } from './Value'

/**
 * Early warning: what a District Disaster Management Authority acts on.
 *
 * Alert level per town, lead time, and where the nearest safe ground is —
 * all computed by the backend from this run. Downloads: a bulletin in English
 * or Hindi, SMS-length texts, and a CAP 1.2 alert (the format behind India's
 * national alert dissemination) that the backend will only issue as an
 * Exercise, never as an Actual warning.
 */

export const LEVEL_STYLE: Record<AlertLevel, { chip: string; label: string }> = {
  RED: { chip: 'bg-rose-600 text-white', label: 'RED' },
  ORANGE: { chip: 'bg-orange-500 text-white', label: 'ORANGE' },
  YELLOW: { chip: 'bg-yellow-300 text-yellow-950', label: 'YELLOW' },
  NONE: { chip: 'bg-slate-200 text-slate-700', label: 'NONE' },
  NOT_ASSESSED: { chip: 'bg-slate-100 text-slate-500 border border-slate-300', label: 'N/A' },
}

export default function WarningPanel({ runId }: { runId: string | null }) {
  const warning = useWarning(runId)
  const [lang, setLang] = useState<'en' | 'hi'>('en')
  const [copied, setCopied] = useState<string | null>(null)

  if (!runId) return null

  return (
    <Panel
      title="Early Warning"
      subtitle="alert level, lead time and nearest safe ground per town"
      action={
        <div className="flex rounded border border-slate-300 text-[10px]">
          {(['en', 'hi'] as const).map((l) => (
            <button
              key={l}
              type="button"
              onClick={() => setLang(l)}
              className={`px-1.5 py-0.5 ${lang === l ? 'bg-slate-800 text-white' : 'text-slate-600'}`}
            >
              {l === 'en' ? 'EN' : 'हिं'}
            </button>
          ))}
        </div>
      }
    >
      {warning.isLoading && <Skeleton className="h-24" />}
      {warning.isError && (
        <p className="text-[11px] text-slate-600">{(warning.error as Error).message}</p>
      )}
      {warning.data && (
        <div className="space-y-2">
          <div className="rounded border border-rose-200 bg-rose-50 px-2 py-1 text-[10px] font-medium text-rose-900">
            {lang === 'en' ? warning.data.disclaimer_en : warning.data.disclaimer_hi}
          </div>

          <ul className="space-y-1.5">
            {warning.data.towns.map((t) => (
              <TownRow key={t.name} town={t} lang={lang} />
            ))}
          </ul>

          <div className="flex flex-wrap gap-1 pt-1">
            <a
              className="rounded bg-slate-800 px-2 py-1 text-[10px] font-medium text-white hover:bg-slate-900"
              href={`/api/results/${runId}/warning/bulletin.txt?lang=en`}
            >
              Bulletin (EN)
            </a>
            <a
              className="rounded bg-slate-800 px-2 py-1 text-[10px] font-medium text-white hover:bg-slate-900"
              href={`/api/results/${runId}/warning/bulletin.txt?lang=hi`}
            >
              बुलेटिन (हिंदी)
            </a>
            <a
              className="rounded border border-slate-400 px-2 py-1 text-[10px] font-medium text-slate-700 hover:bg-slate-50"
              href={`/api/results/${runId}/warning/cap.xml`}
              title="OASIS Common Alerting Protocol 1.2, status Exercise"
            >
              CAP 1.2 alert (.xml)
            </a>
          </div>

          {(lang === 'en' ? warning.data.sms : warning.data.sms_hi).length > 0 && (
            <details className="text-[10px]">
              <summary className="cursor-pointer text-slate-600">SMS texts</summary>
              <ul className="mt-1 space-y-1">
                {(lang === 'en' ? warning.data.sms : warning.data.sms_hi).map((m) => (
                  <li key={m.town} className="rounded bg-slate-50 p-1.5">
                    <div className="font-mono text-slate-800">{m.text}</div>
                    <div className="mt-0.5 flex items-center justify-between text-slate-400">
                      <span>
                        {m.chars} chars · {m.segments} SMS segment{m.segments > 1 ? 's' : ''}
                      </span>
                      <button
                        type="button"
                        className="text-sky-700 hover:underline"
                        onClick={() => {
                          navigator.clipboard?.writeText(m.text).catch(() => {})
                          setCopied(m.town)
                        }}
                      >
                        {copied === m.town ? 'copied ✓' : 'copy'}
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </details>
          )}

          <details className="text-[10px] leading-relaxed text-slate-500">
            <summary className="cursor-pointer">How these levels are set</summary>
            <p className="mt-1">{warning.data.convention}</p>
            <p className="mt-1">{warning.data.safe_ground_method}</p>
          </details>
        </div>
      )}
    </Panel>
  )
}

function TownRow({ town, lang }: { town: TownAlert; lang: 'en' | 'hi' }) {
  const style = LEVEL_STYLE[town.level]
  const flooded = town.level === 'RED' || town.level === 'ORANGE' || town.level === 'YELLOW'
  return (
    <li className="rounded border border-slate-100 p-1.5">
      <div className="flex items-center gap-1.5">
        <span className={`rounded px-1.5 py-0.5 text-[9px] font-bold ${style.chip}`}>
          {style.label}
        </span>
        <span className="text-xs font-medium text-slate-900">{town.name}</span>
        <span className="ml-auto text-[10px] text-slate-600">
          {lang === 'en' ? town.action_en : town.action_hi}
        </span>
      </div>
      {flooded && (
        <div className="mt-1 grid grid-cols-3 gap-1 text-[10px] text-slate-600">
          <span>
            <span className="text-slate-400">arrives </span>
            <strong className="tabular-nums text-slate-900">{formatMinutes(town.arrival_min)}</strong>
          </span>
          <span>
            <span className="text-slate-400">depth </span>
            <strong className="tabular-nums text-slate-900">
              {town.max_depth_m === null ? NOT_COMPUTED : `${formatNumber(town.max_depth_m, 1)} m`}
            </strong>
          </span>
          <span>
            <span className="text-slate-400">hazard </span>
            <strong className="text-slate-900">{town.hazard_class ?? NOT_COMPUTED}</strong>
          </span>
        </div>
      )}
      {flooded && (
        <div className="mt-0.5 text-[10px] text-emerald-800">
          {town.safe_ground ? (
            <>
              ⇗ Safe ground {formatNumber(town.safe_ground.distance_km, 1)} km{' '}
              {town.safe_ground.direction} (straight line),{' '}
              {formatNumber(town.safe_ground.height_above_flood_m, 0)} m above the flood
            </>
          ) : (
            <span className="text-slate-500">
              Safe ground: {NOT_COMPUTED} {town.safe_ground_reason && `(${town.safe_ground_reason})`}
            </span>
          )}
        </div>
      )}
    </li>
  )
}
