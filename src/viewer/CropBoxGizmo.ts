import * as THREE from 'three'
import { TransformControls } from 'three/examples/jsm/controls/TransformControls.js'
import { boxFromTransform, transformFromBox, type Box } from './cropBoxMath.ts'

export interface GizmoDeps {
  camera: THREE.Camera
  domElement: HTMLElement
  /** Where the gizmo helper is added — the scene root, not the splat mesh. */
  scene: THREE.Object3D
  /** The splat mesh. The box proxy is parented here so its local transform is
   *  already in backend coordinates (the Y-flip belongs to this parent). */
  parent: THREE.Object3D
  setOrbitEnabled: (on: boolean) => void
}

/**
 * Movable/resizable crop box.
 *
 * Orbit is disabled only for the duration of a handle drag. That is the single
 * sanctioned exception to "the mouse always orbits" — it is scoped to an active
 * drag, so there is no mode the operator can get stuck in, and `detach()`
 * restores orbit even if the drag never ended (tool switched mid-drag).
 */
export class CropBoxGizmo {
  onChange: ((box: Box) => void) | null = null

  private controls: TransformControls
  private proxy: THREE.Mesh | null = null
  private dragging = false
  // Captured once, not re-read via getHelper() in dispose(): in three r184
  // TransformControls.dispose() does not remove the helper from the scene
  // itself, so dispose() must remove the SAME object it added (fix pass 2,
  // MINOR 4) rather than assume getHelper() is idempotent.
  private helper: THREE.Object3D

  constructor(private deps: GizmoDeps) {
    this.controls = new TransformControls(deps.camera, deps.domElement)
    // three r184 types the event's `value` as `unknown`; it is the drag flag.
    this.controls.addEventListener('dragging-changed', (e: { value: unknown }) => {
      const dragging = e.value === true
      this.dragging = dragging
      deps.setOrbitEnabled(!dragging)
    })
    this.controls.addEventListener('objectChange', () => this.emit())
    this.helper = this.controls.getHelper()
    deps.scene.add(this.helper)
  }

  attach(box: Box): void {
    this.detach()
    const t = transformFromBox(box)
    const proxy = new THREE.Mesh(
      new THREE.BoxGeometry(1, 1, 1),
      new THREE.MeshBasicMaterial({ visible: false }),
    )
    proxy.position.set(t.position[0], t.position[1], t.position[2])
    proxy.scale.set(t.scale[0], t.scale[1], t.scale[2])
    this.deps.parent.add(proxy)
    this.proxy = proxy
    this.controls.attach(proxy)
    this.emit()
  }

  detach(): void {
    this.detachProxy()
    if (this.dragging) {
      // A tool switch mid-drag never fires dragging-changed:false, which would
      // leave orbit disabled forever — exactly the nav trap the editor fixed.
      this.dragging = false
      this.deps.setOrbitEnabled(true)
    }
  }

  getBox(): Box | null {
    if (!this.proxy) return null
    const p = this.proxy.position, s = this.proxy.scale
    return boxFromTransform([p.x, p.y, p.z], [s.x, s.y, s.z])
  }

  setMode(mode: 'translate' | 'scale'): void {
    this.controls.setMode(mode)
  }

  dispose(): void {
    this.detach()
    // TransformControls.dispose() (r184) does not remove its helper from the
    // scene — without this, every reload while the crop tool is active (now
    // that dispose() runs on every reload) leaks an orphan root that is still
    // traversed every frame (fix pass 2, MINOR 4).
    this.deps.scene.remove(this.helper)
    this.controls.dispose()
  }

  private emit(): void {
    const box = this.getBox()
    if (box && this.onChange) this.onChange(box)
  }

  private detachProxy(): void {
    this.controls.detach()
    if (this.proxy) {
      this.deps.parent.remove(this.proxy)
      this.proxy.geometry.dispose()
      ;(this.proxy.material as THREE.Material).dispose()
    }
    this.proxy = null
  }
}
