import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import PlaybackSpeed, { frameIntervalMs } from './PlaybackSpeed'

describe('PlaybackSpeed', () => {
  it('maps speed to the frame interval', () => {
    expect(frameIntervalMs(1)).toBe(700)
    expect(frameIntervalMs(2)).toBe(350)
    expect(frameIntervalMs(0.5)).toBe(1400)
    expect(frameIntervalMs(0)).toBe(700)
  })

  it('marks the current speed and reports a change', () => {
    const onChange = vi.fn()
    render(<PlaybackSpeed speed={2} onChange={onChange} />)
    expect(screen.getByRole('button', { name: '2×' })).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getByRole('button', { name: '4×' }))
    expect(onChange).toHaveBeenCalledWith(4)
  })
})
