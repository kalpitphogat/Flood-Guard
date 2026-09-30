import { fireEvent, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { mockFetch, renderWithQuery } from '../test/utils'
import ProvenancePanel from './ProvenancePanel'

describe('ProvenancePanel', () => {
  it('shows cautions first and every value with its source field', async () => {
    mockFetch({
      '/provenance': {
        body: {
          run_id: 'r',
          labels: [{ level: 'caution', text: 'Reservoir bathymetry is RECONSTRUCTED, not surveyed.', source: 'max_depth.tif:FG_RESERVOIR' }],
          sections: [{ title: 'Solver', rows: [{ label: 'CFL', value: 0.45, source: 'max_depth.tif:FG_CFL' }] }],
        },
      },
    })
    renderWithQuery(<ProvenancePanel runId="r" />)
    expect(await screen.findByTestId('provenance-labels')).toHaveTextContent('RECONSTRUCTED')
    expect(screen.queryByText('max_depth.tif:FG_CFL')).toBeNull()
    fireEvent.click(screen.getByText('Show all'))
    expect(screen.getByText('max_depth.tif:FG_CFL')).toBeInTheDocument()
  })
})
