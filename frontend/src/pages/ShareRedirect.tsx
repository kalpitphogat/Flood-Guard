import { useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useResolveShare } from '../api/hooks'

/** /s/:code — resolve a short link and open the run in the dashboard. */
export default function ShareRedirect() {
  const { code } = useParams()
  const share = useResolveShare(code)
  const navigate = useNavigate()

  useEffect(() => {
    if (!share.data) return
    const params = new URLSearchParams({ run: share.data.run_id })
    const { layer, engine, frame, tab } = share.data.view ?? {}
    if (layer) params.set('layer', layer)
    if (engine) params.set('engine', engine)
    if (frame !== undefined && frame !== null) params.set('frame', String(frame))
    if (tab) params.set('tab', tab)
    navigate(`/simulation?${params}`, { replace: true })
  }, [share.data, navigate])

  return (
    <div className="mx-auto max-w-md px-4 py-16 text-center text-sm text-slate-600">
      {share.isError ? (
        <p>
          This share link is not valid on this server: {(share.error as Error).message}
        </p>
      ) : (
        <p>Opening shared simulation…</p>
      )}
    </div>
  )
}
