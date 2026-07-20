/**
 * World-pinned markers + auto-drawn breadcrumb trail.
 *
 * Everything lives inside the renderer's overlay group (additive hook on
 * SceneManager). The group inherits the SAME Y-flip the splat mesh uses
 * (rotation.x = PI) so marker/trail positions are expressed in the backend's
 * raw splat coordinate frame and visually coincide with the Gaussians.
 */
import * as THREE from 'three'
import type { RendererBridge } from './types.ts'

const MARKER_COLOR = 0x36d399
const TRAIL_COLOR = 0x5b8cff
const TRAIL_MAX_POINTS = 512

interface Marker {
  group: THREE.Group
  label: string
}

export class Overlay {
  private root: THREE.Group
  private markersGroup = new THREE.Group()
  private markers: Marker[] = []

  private trailGroup = new THREE.Group()
  private trailPositions: number[] = []
  private trailLine: THREE.Line
  private trailGeom: THREE.BufferGeometry
  private trailAttr: THREE.BufferAttribute

  constructor(bridge: RendererBridge) {
    this.root = bridge.getOverlayGroup()
    // Markers are given in the backend's raw splat frame, so they inherit the
    // same Y-flip the splat mesh uses (COLMAP Y-down → Three Y-up) and land on
    // the Gaussians. The trail traces the camera's WORLD path, so it stays
    // unflipped.
    this.markersGroup.rotation.x = Math.PI
    this.root.add(this.markersGroup)
    this.root.add(this.trailGroup)

    this.trailGeom = new THREE.BufferGeometry()
    this.trailAttr = new THREE.BufferAttribute(new Float32Array(TRAIL_MAX_POINTS * 3), 3)
    this.trailAttr.setUsage(THREE.DynamicDrawUsage)
    this.trailGeom.setAttribute('position', this.trailAttr)
    this.trailGeom.setDrawRange(0, 0)
    this.trailLine = new THREE.Line(
      this.trailGeom,
      new THREE.LineBasicMaterial({ color: TRAIL_COLOR, transparent: true, opacity: 0.8 }),
    )
    this.trailLine.frustumCulled = false
    this.trailGroup.add(this.trailLine)
  }

  /** Drop a labeled, world-pinned marker. */
  dropMarker(position: [number, number, number], label: string): void {
    const group = new THREE.Group()
    group.position.set(position[0], position[1], position[2])

    const dot = new THREE.Mesh(
      new THREE.SphereGeometry(0.03, 16, 12),
      new THREE.MeshBasicMaterial({ color: MARKER_COLOR }),
    )
    group.add(dot)
    if (label) group.add(this.makeLabelSprite(label))

    this.markersGroup.add(group)
    this.markers.push({ group, label })
  }

  clearMarkers(): void {
    for (const m of this.markers) {
      this.markersGroup.remove(m.group)
      m.group.traverse((o) => {
        if (o instanceof THREE.Mesh || o instanceof THREE.Sprite) {
          o.geometry?.dispose?.()
          const mat = o.material as THREE.Material | THREE.Material[]
          if (Array.isArray(mat)) mat.forEach((x) => x.dispose())
          else mat.dispose()
        }
      })
    }
    this.markers = []
  }

  /** Append a point to the breadcrumb trail (called automatically on moves). */
  pushTrailPoint(position: THREE.Vector3): void {
    const last = this.trailPositions.length
    if (last >= 3) {
      const dx = position.x - this.trailPositions[last - 3]
      const dy = position.y - this.trailPositions[last - 2]
      const dz = position.z - this.trailPositions[last - 1]
      if (dx * dx + dy * dy + dz * dz < 1e-4) return // skip near-duplicate
    }
    if (this.trailPositions.length >= TRAIL_MAX_POINTS * 3) {
      this.trailPositions.splice(0, 3)
    }
    this.trailPositions.push(position.x, position.y, position.z)

    const count = this.trailPositions.length / 3
    this.trailAttr.array.set(this.trailPositions)
    this.trailAttr.needsUpdate = true
    this.trailGeom.setDrawRange(0, count)
  }

  resetTrail(): void {
    this.trailPositions = []
    this.trailGeom.setDrawRange(0, 0)
    this.trailAttr.needsUpdate = true
  }

  dispose(): void {
    this.clearMarkers()
    this.resetTrail()
    this.root.remove(this.markersGroup)
    this.root.remove(this.trailGroup)
    this.trailGeom.dispose()
    ;(this.trailLine.material as THREE.Material).dispose()
  }

  private makeLabelSprite(text: string): THREE.Sprite {
    const pad = 8
    const font = 28
    const canvas = document.createElement('canvas')
    const ctx = canvas.getContext('2d')!
    ctx.font = `${font}px sans-serif`
    const w = Math.ceil(ctx.measureText(text).width) + pad * 2
    const h = font + pad * 2
    canvas.width = w
    canvas.height = h
    ctx.font = `${font}px sans-serif`
    ctx.fillStyle = 'rgba(8,10,18,0.78)'
    ctx.fillRect(0, 0, w, h)
    ctx.fillStyle = '#e6f0ff'
    ctx.textBaseline = 'middle'
    ctx.fillText(text, pad, h / 2)

    const texture = new THREE.CanvasTexture(canvas)
    texture.minFilter = THREE.LinearFilter
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, depthTest: false }))
    const scale = 0.0025
    sprite.scale.set(w * scale, h * scale, 1)
    sprite.position.set(0, 0.08, 0)
    return sprite
  }
}
