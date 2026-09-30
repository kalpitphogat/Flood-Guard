import { useState } from 'react'

/** Stops a live run: the server kills the worker process at once. */
export default function StopButton({ jobId }: { jobId: string | null }) {
  const [stopping, setStopping] = useState(false)
  return (
    <button
      type="button"
      disabled={!jobId || stopping}
      onClick={() => {
        setStopping(true)
        fetch(`/api/jobs/${jobId}/cancel`, { method: 'POST' }).catch(() => setStopping(false))
      }}
      className="w-full rounded border border-rose-300 py-1 text-[11px] font-medium
                 text-rose-700 hover:bg-rose-50 disabled:opacity-60"
    >
      {stopping ? 'Stopping…' : 'Stop run'}
    </button>
  )
}
