import { describe, it, expect } from 'vitest'
import { proposalTitle } from './proposalTitle'

describe('proposalTitle', () => {
  it('maps crop_outside_box to the crop question', () => {
    expect(proposalTitle('crop_outside_box')).toBe('Crop to this box?')
  })

  it('maps delete_selection to the delete question', () => {
    expect(proposalTitle('delete_selection')).toBe('Delete the highlighted splats?')
  })

  it('falls back to a generic question for unknown kinds', () => {
    expect(proposalTitle('some_future_kind')).toBe('Apply this edit?')
  })
})
