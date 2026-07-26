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

  constructor(private deps: GizmoDeps) {
    this.controls = new TransformControls(deps.camera, deps.domElement)
    this.controls.addEventListener('dragging-changed', (e: { value: boolean }) => {
      this.dragging = e.value
      deps.setOrbitEnabled(!e.value)
    })
    this.controls.addEventListener('objectChange', () => this.emit())
    deps.scene.add(this.controls.getHelper())
  }

  attach(box: Box): void {
    this.detachProxy()
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
