/** Speeds offered for the flood animation; 1× is one stored frame every 700 ms. */
export const PLAYBACK_SPEEDS = [0.5, 1, 2, 4] as const
export const BASE_FRAME_MS = 700

/** Milliseconds between animation frames at a given speed. */
export function frameIntervalMs(speed: number): number {
  return Math.round(BASE_FRAME_MS / (speed > 0 ? speed : 1))
}

/**
 * Speed pills under the time slider. Changing speed only changes how often the
 * next stored frame is shown; the frames themselves (and their times) are the
 * solver's own output.
 */
export default function PlaybackSpeed({
  speed,
  onChange,
  disabled,
}: {
  speed: number
  onChange: (speed: number) => void
  disabled?: boolean
}) {
  return (
    <div className="flex items-center gap-0.5" role="group" aria-label="Playback speed">
      {PLAYBACK_SPEEDS.map((s) => (
        <button
          key={s}
          type="button"
          disabled={disabled}
          aria-pressed={s === speed}
          onClick={() => onChange(s)}
          className={`rounded px-1.5 py-0.5 text-[10px] disabled:opacity-50 ${
            s === speed
              ? 'bg-sky-700 font-medium text-white'
              : 'border border-slate-300 text-slate-600 hover:bg-slate-50'
          }`}
        >
          {s}×
        </button>
      ))}
    </div>
  )
}
