/** Kind → operator-facing question for a parked proposal. Pure, so it can be
 *  unit-tested without React and shared without tripping fast-refresh. */
export function proposalTitle(kind: string): string {
  switch (kind) {
    case 'delete_selection':
      return 'Delete the highlighted splats?'
    case 'keep_only_selection':
      return 'Keep ONLY the highlighted splats — delete everything else?'
    case 'bulk_edit':
      return 'Run this scene-wide cleanup?'
    case 'delete_clusters':
      return 'Delete the junk clusters the tour flagged?'
    case 'keep_only_subject':
      return 'Delete the highlighted splats — keep the rest of the scene?'
    default:
      return 'Apply this edit?'
  }
}
