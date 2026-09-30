import { fireEvent, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { mockFetch, renderWithQuery } from '../test/utils'
import LifeLossPanel from './LifeLossPanel'

const BASE = {
  method: 'Graham (1999) flood-severity method, USBR DSO-99-06, Table 7',
  citation: 'Graham, W.J. (1999). DSO-99-06.',
  caveats: ['An order-of-magnitude planning estimate, not a prediction.'],
}

describe('LifeLossPanel', () => {
  it('shows a range with the method and caveats, never a bare number', async () => {
    mockFetch({
      '/life-loss': {
        body: { ...BASE, computed: true, population_at_risk: 1000, estimate: 150,
                range: [30, 350], par_without_a_rate: 0, notes: [] },
      },
    })
    renderWithQuery(<LifeLossPanel runId="r1" />)
    expect(await screen.findByTestId('life-loss-range')).toHaveTextContent('30–350')
    fireEvent.click(screen.getByText(/Show method and caveats/))
    expect(screen.getByText(/not a prediction/)).toBeInTheDocument()
  })

  it('says why when it is not computed, and shows no number', async () => {
    mockFetch({
      '/life-loss': {
        body: { ...BASE, computed: false, range: [null, null],
                reason: 'No population raster is available on this machine.' },
      },
    })
    renderWithQuery(<LifeLossPanel runId="r1" />)
    expect(await screen.findByTestId('life-loss-not-computed')).toHaveTextContent(
      'No population raster',
    )
    expect(screen.queryByTestId('life-loss-range')).toBeNull()
  })
})
