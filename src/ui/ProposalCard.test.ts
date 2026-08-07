import { describe, it, expect } from 'vitest'
import { proposalTitle } from './proposalTitle'

describe('proposalTitle', () => {
  it('maps crop_outside_box to the crop question', () => {
    expect(proposalTitle('crop_outside_box')).toBe('Crop to this box?')
  })

  it('maps delete_selection to the delete question', () => {
    expect(proposalTitle('delete_selection')).toBe('Delete the highlighted splats?')
  })

  it('maps bulk_edit to the scene-wide cleanup question', () => {
    expect(proposalTitle('bulk_edit')).toBe('Run this scene-wide cleanup?')
  })

  it('maps keep_only_selection to the inverse-delete question — the consent difference must be explicit', () => {
    expect(proposalTitle('keep_only_selection')).toBe(
      'Keep ONLY the highlighted splats — delete everything else?',
    )
  })

  it('maps delete_clusters to the judgment-tour batch question (v0.7)', () => {
    expect(proposalTitle('delete_clusters')).toBe('Delete the junk clusters the tour flagged?')
  })

  it('maps keep_only_subject to the subject lock-on question (v0.8)', () => {
    expect(proposalTitle('keep_only_subject')).toBe(
      'Keep the highlighted subject — delete everything else?',
    )
  })

  it('falls back to a generic question for unknown kinds', () => {
    expect(proposalTitle('some_future_kind')).toBe('Apply this edit?')
  })
})
