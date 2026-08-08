import { describe, it, expect } from 'vitest'
import { proposalTitle } from './proposalTitle'

describe('proposalTitle', () => {
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

  it('maps keep_only_subject to the subject lock-on question (v0.8 — the tint marks the DELETE-set)', () => {
    expect(proposalTitle('keep_only_subject')).toBe(
      'Delete the highlighted splats — keep the rest of the scene?',
    )
  })

  it('falls back to a generic question for unknown kinds', () => {
    expect(proposalTitle('some_future_kind')).toBe('Apply this edit?')
  })
})
