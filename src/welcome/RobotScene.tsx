import { useEffect, useRef } from 'react'
import * as THREE from 'three'

interface RobotSceneProps {
  activeCardRef: React.RefObject<HTMLElement | null>
}

export default function RobotScene({ activeCardRef }: RobotSceneProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const cvs = canvasRef.current
    if (!cvs) return

    const C = { cyan: 0x34c8ff, orange: 0xf9a23b, body: 0x12161d, bodyLite: 0x1b212b, dark: 0x080a0e }

    const renderer = new THREE.WebGLRenderer({ canvas: cvs, antialias: true, alpha: true })
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2))

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(45, innerWidth / innerHeight, 0.1, 100)
    camera.position.set(0, 0.2, 8.4)
    camera.lookAt(0, 0, 0)

    /* ── Lighting ── */
    scene.add(new THREE.AmbientLight(0x3a4658, 0.55))
    const k = new THREE.DirectionalLight(0xcfe9ff, 0.7); k.position.set(-4, 5, 6); scene.add(k)
    const rim = new THREE.DirectionalLight(C.cyan, 1.1); rim.position.set(5, 2, -4); scene.add(rim)
    const core = new THREE.PointLight(C.orange, 1.3, 14); core.position.set(0, -0.2, 1.6); scene.add(core)

    /* ── Helpers ── */
    const metal = (c: number) => new THREE.MeshStandardMaterial({ color: c, metalness: .6, roughness: .42 })
    const glow = (c: number, i = 1.4) => new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: i, metalness: .2, roughness: .4 })
    const bx = (w: number, h: number, d: number, m: THREE.Material) => new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m)
    const cy = (rt: number, rb: number, h: number, m: THREE.Material, s = 24) => new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, s), m)
    const sp = (r: number, m: THREE.Material, s = 24) => new THREE.Mesh(new THREE.SphereGeometry(r, s, s), m)

    /* ── Robot rig ── */
    const robot = new THREE.Group(); scene.add(robot)
    const robotBaseY = -0.35; robot.position.y = robotBaseY

    // torso
    const torso = bx(1.5, 1.35, 0.95, metal(C.body)); robot.add(torso)
    const chestSeam = bx(0.9, 0.06, 0.02, glow(C.cyan, 1.2)); chestSeam.position.set(0, 0.34, 0.49); robot.add(chestSeam)
    const reactor = sp(0.17, glow(C.orange, 1.8)); reactor.position.set(0, -0.05, 0.49); robot.add(reactor)
    const reactorRing = new THREE.Mesh(new THREE.TorusGeometry(0.24, 0.03, 12, 32), glow(C.orange, 1.0))
    reactorRing.position.set(0, -0.05, 0.46); robot.add(reactorRing)

    // hips / legs
    const hips = bx(1.1, 0.4, 0.8, metal(C.bodyLite)); hips.position.y = -0.95; robot.add(hips)
    ;[-0.38, 0.38].forEach(x => {
      const leg = cy(0.18, 0.2, 0.7, metal(C.body)); leg.position.set(x, -1.5, 0); robot.add(leg)
      const foot = bx(0.42, 0.18, 0.62, metal(C.bodyLite)); foot.position.set(x, -1.92, 0.07); robot.add(foot)
    })

    // neck + head
    const neck = cy(0.16, 0.16, 0.18, metal(C.bodyLite)); neck.position.y = 0.82; robot.add(neck)
    const head = new THREE.Group(); head.position.y = 1.18; robot.add(head)
    const skull = bx(1.0, 0.78, 0.82, metal(C.bodyLite)); head.add(skull)
    const visor = bx(0.84, 0.4, 0.06, new THREE.MeshStandardMaterial({ color: C.dark, metalness: .7, roughness: .25 }))
    visor.position.set(0, 0.02, 0.42); head.add(visor)
    const eyeMat = glow(C.cyan, 2.2)
    const eyeL = bx(0.2, 0.22, 0.05, eyeMat); eyeL.position.set(-0.2, 0.03, 0.46); head.add(eyeL)
    const eyeR = bx(0.2, 0.22, 0.05, eyeMat); eyeR.position.set(0.2, 0.03, 0.46); head.add(eyeR)
    const ant = cy(0.025, 0.025, 0.42, metal(C.bodyLite)); ant.position.set(0, 0.62, 0); head.add(ant)
    const antTip = sp(0.07, glow(C.cyan, 2.0)); antTip.position.set(0, 0.86, 0); head.add(antTip)

    // left idle arm
    const armL = new THREE.Group(); armL.position.set(-0.92, 0.34, 0); robot.add(armL)
    armL.add(sp(0.22, metal(C.bodyLite)))
    const foreL = cy(0.13, 0.15, 0.8, metal(C.body)); foreL.position.set(0, -0.5, 0); armL.add(foreL)
    const handL = sp(0.16, metal(C.bodyLite)); handL.position.set(0, -0.95, 0); armL.add(handL)
    armL.rotation.z = 0.12

    // right arm = CANNON
    const shoulder = new THREE.Group(); shoulder.position.set(0.92, 0.34, 0); robot.add(shoulder)
    shoulder.add(sp(0.24, metal(C.bodyLite)))
    const cannon = new THREE.Group(); shoulder.add(cannon)
    const upper = cy(0.16, 0.16, 0.7, metal(C.body)); upper.rotation.x = Math.PI / 2; upper.position.z = 0.35; cannon.add(upper)
    const barrel = cy(0.2, 0.16, 0.6, metal(C.bodyLite)); barrel.rotation.x = Math.PI / 2; barrel.position.z = 0.95; cannon.add(barrel)
    const muzzleRing = new THREE.Mesh(new THREE.TorusGeometry(0.16, 0.035, 12, 24), glow(C.cyan, 1.6))
    muzzleRing.position.z = 1.2; cannon.add(muzzleRing)
    const emitter = new THREE.Object3D(); emitter.position.z = 1.28; cannon.add(emitter)
    const muzzleGlow = sp(0.09, glow(C.cyan, 2.4)); muzzleGlow.position.z = 1.28; muzzleGlow.visible = false; cannon.add(muzzleGlow)

    // rest pose
    const REST = new THREE.Vector3(0.15, -1, 0.35).normalize()
    const FWD = new THREE.Vector3(0, 0, 1)
    function aimQuat(dirWorld: THREE.Vector3) {
      const local = dirWorld.clone()
      const inv = shoulder.getWorldQuaternion(new THREE.Quaternion()).invert()
      local.applyQuaternion(inv).normalize()
      return new THREE.Quaternion().setFromUnitVectors(FWD, local)
    }
    let targetQuat = aimQuat(REST.clone())
    cannon.quaternion.copy(targetQuat)

    /* ── Laser beam ── */
    const beamMat = new THREE.MeshBasicMaterial({ color: C.cyan, transparent: true, opacity: 0.0, blending: THREE.AdditiveBlending })
    const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 1, 12), beamMat)
    beam.visible = false; scene.add(beam)
    const beamCoreMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0, blending: THREE.AdditiveBlending })
    const beamCore = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, 1, 8), beamCoreMat)
    beamCore.visible = false; scene.add(beamCore)

    function placeBeam(mesh: THREE.Mesh, a: THREE.Vector3, b: THREE.Vector3, w: number) {
      const dir = new THREE.Vector3().subVectors(b, a)
      const len = dir.length()
      mesh.position.copy(a).addScaledVector(dir, 0.5)
      mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.clone().normalize())
      mesh.scale.set(w, len, w)
    }

    /* ── Targeting ── */
    const zPlane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0)
    const ray = new THREE.Raycaster()
    let aimWorld: THREE.Vector3 | null = null

    function cardToWorld(card: HTMLElement) {
      const r = card.getBoundingClientRect()
      const cx = r.left + r.width / 2, ccy = r.top + r.height / 2
      const ndc = new THREE.Vector2((cx / innerWidth) * 2 - 1, -(ccy / innerHeight) * 2 + 1)
      ray.setFromCamera(ndc, camera)
      const hit = new THREE.Vector3()
      ray.ray.intersectPlane(zPlane, hit)
      return hit
    }

    // cursor tracking
    let mouseWorld = new THREE.Vector3()
    const onPointerMove = (e: PointerEvent) => {
      const ndc = new THREE.Vector2((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1)
      ray.setFromCamera(ndc, camera)
      ray.ray.intersectPlane(zPlane, mouseWorld)
    }
    window.addEventListener('pointermove', onPointerMove)

    /* ── Animation ── */
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches
    let t = 0, blink = 0, nextBlink = 2 + Math.random() * 3
    let animId = 0

    function tick() {
      animId = requestAnimationFrame(tick)
      t += 0.016

      const activeCard = activeCardRef.current
      const firing = activeCard !== null

      // idle bob + sway
      if (!reduce) {
        robot.position.y = robotBaseY + Math.sin(t * 1.6) * 0.05
        robot.rotation.y = Math.sin(t * 0.5) * 0.12
      }

      // head tracks cursor or target
      const watch = (firing && aimWorld) ? aimWorld : mouseWorld
      if (watch) {
        const hp = head.getWorldPosition(new THREE.Vector3())
        const look = watch.clone().sub(hp); look.z = Math.abs(look.z) || 1
        head.rotation.y = THREE.MathUtils.clamp(Math.atan2(look.x, look.z), -0.6, 0.6) - robot.rotation.y
        head.rotation.x = THREE.MathUtils.clamp(-Math.atan2(look.y, 4), -0.3, 0.3)
      }

      // blink
      blink += 0.016
      if (blink > nextBlink) {
        const p = (blink - nextBlink) / 0.12
        eyeL.scale.y = eyeR.scale.y = Math.max(0.1, Math.abs(Math.cos(p * Math.PI)))
        if (p >= 1) { blink = 0; nextBlink = 2 + Math.random() * 3; eyeL.scale.y = eyeR.scale.y = 1 }
      }

      // pulse
      ;(antTip.material as THREE.MeshStandardMaterial).emissiveIntensity = 1.6 + Math.sin(t * 3) * 0.5
      ;(reactor.material as THREE.MeshStandardMaterial).emissiveIntensity = 1.6 + Math.sin(t * 2.2) * 0.4

      // aim cannon
      if (firing && activeCard) {
        aimWorld = cardToWorld(activeCard)
        const sw = shoulder.getWorldPosition(new THREE.Vector3())
        const dir = aimWorld.clone().sub(sw).normalize()
        targetQuat = aimQuat(dir)
        muzzleGlow.visible = true
      } else {
        targetQuat = aimQuat(REST.clone())
        muzzleGlow.visible = false
      }
      cannon.quaternion.slerp(targetQuat, reduce ? 1 : 0.22)

      // beam
      const ew = emitter.getWorldPosition(new THREE.Vector3())
      const lit = firing && aimWorld !== null
      beam.visible = beamCore.visible = (beamMat.opacity > 0.02 || lit)
      beamMat.opacity = THREE.MathUtils.lerp(beamMat.opacity, lit ? 0.7 : 0, 0.3)
      beamCoreMat.opacity = THREE.MathUtils.lerp(beamCoreMat.opacity, lit ? 0.95 : 0, 0.3)
      if (beam.visible) {
        const end = lit ? aimWorld! : ew.clone().add(new THREE.Vector3(0, -1, 0))
        const flick = 1 + (lit ? Math.sin(t * 60) * 0.12 : 0)
        placeBeam(beam, ew, end, 1 * flick)
        placeBeam(beamCore, ew, end, 1)
        ;(muzzleGlow.material as THREE.MeshStandardMaterial).emissiveIntensity = 2.2 + Math.sin(t * 40) * 0.8
      }

      renderer.render(scene, camera)
    }
    tick()

    const onResize = () => {
      renderer.setSize(innerWidth, innerHeight)
      camera.aspect = innerWidth / innerHeight
      camera.updateProjectionMatrix()
    }
    window.addEventListener('resize', onResize)
    onResize()

    return () => {
      cancelAnimationFrame(animId)
      window.removeEventListener('resize', onResize)
      window.removeEventListener('pointermove', onPointerMove)
      renderer.dispose()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return <canvas ref={canvasRef} className="fixed inset-0 z-[1]" style={{ pointerEvents: 'none' }} />
}
