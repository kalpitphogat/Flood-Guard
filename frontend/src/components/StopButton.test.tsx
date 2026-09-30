import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import StopButton from './StopButton'

describe('StopButton', () => {
  it('posts the cancel request once and shows that it is stopping', () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}'))
    vi.stubGlobal('fetch', fetchMock)
    render(<StopButton jobId="abc" />)
    fireEvent.click(screen.getByRole('button', { name: 'Stop run' }))
    expect(fetchMock).toHaveBeenCalledWith('/api/jobs/abc/cancel', { method: 'POST' })
    expect(screen.getByRole('button', { name: 'Stopping…' })).toBeDisabled()
    vi.unstubAllGlobals()
  })
})
