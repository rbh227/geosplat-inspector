/** Kind → operator-facing question for a parked proposal. Pure, so it can be
 *  unit-tested without React and shared without tripping fast-refresh. */
export function proposalTitle(kind: string): string {
  switch (kind) {
    case 'crop_outside_box':
      return 'Crop to this box?'
    case 'delete_selection':
      return 'Delete the highlighted splats?'
    case 'bulk_edit':
      return 'Run this scene-wide cleanup?'
    default:
      return 'Apply this edit?'
  }
}
