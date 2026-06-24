import { GoogleGenerativeAI } from '@google/generative-ai'
import * as THREE from 'three'
import { AGENT_TOOLS } from './tools'
import { RateLimiter, withRetry } from './rate-limiter'
import type { AgentAction } from '../types/agent'
import type { ViewerHandle } from '../types/viewer'

/* -------------------------------------------------------------------------- */
/*  Types                                                                     */
/* -------------------------------------------------------------------------- */

interface AgentConfig {
  model: string
  maxSteps: number
}

/** API-agnostic tool execution result */
interface ToolExecResult {
  text: string
  image?: string // raw base64 JPEG (no data: prefix)
  finalAnswer?: string
}

/* -------------------------------------------------------------------------- */
/*  System prompt                                                             */
/* -------------------------------------------------------------------------- */

const SYSTEM_PROMPT = `You are GeoSplat Inspector, an AI assistant that helps users explore and clean up 3D Gaussian splat scenes.

You are looking at a LIVE 3D scene that the user has loaded. You can see it by capturing frames. You MUST use your tools to look at and interact with the actual scene before answering ANY question. NEVER give generic or textbook answers — always base your response on what you actually observe in this specific scene.

## CRITICAL RULE
Before answering ANY user question — even simple ones — you MUST:
1. Call get_scene_stats to read the actual data
2. Call capture_frame to see what the scene looks like right now
Only then respond, and your response must reference what you actually saw and measured. If the user says "the splat", "this scene", "it", etc., they mean the loaded file you are looking at.

## Exploration Protocol
When asked to explore or describe the scene:
1. Call get_scene_stats FIRST to understand the data distribution
2. Capture a frame to see the current view
3. Move the camera to different angles (top, front, iso) to get a complete picture
4. Describe what you observe, referencing the stats

## Cleanup Strategy
When asked to clean up, follow this protocol:

### Step 1: Assess
- Call get_scene_stats to understand the data
- Capture a frame from the current view + a top-down view
- Identify the scene type:
  - AERIAL/DRONE: expect sky artifacts above, ground noise below, edge floaters
  - OBJECT SCAN: expect background noise, fewer sky artifacts
  - INDOOR: expect window blowout, wall edge artifacts
- Announce your cleanup plan to the user BEFORE executing

### Step 2: Execute in Order
Apply operations from least to most destructive:
1. **Opacity filter** (clean_opacity): Always start here. Remove semi-transparent haze. Threshold 0.02-0.05 for gentle, 0.1-0.2 for aggressive.
2. **Height filter** (filter_by_height): If aerial scene, clip sky (set max_y above main content) and underground (set min_y below ground plane). Use bbox from stats.
3. **Scale filter** (filter_by_scale): Remove oversized blob splats. Use scale distribution from stats to pick max_scale.
4. **Color filter** (filter_by_color): If sky artifacts visible, target sky blue (r=0.53, g=0.81, b=0.98, tolerance=0.2). Only use if you can see color-specific artifacts.
5. **Density filter** (filter_by_density): THE most effective tool for floaters. Use estimated_density_radius from stats. Start with min_neighbors=3, increase to 5-8 for aggressive.
6. **Outlier removal** (remove_outliers): Final pass for remaining distant outliers. k=3-5.

### Step 3: Verify
- Capture a frame after EACH cleanup step
- Compare splat count before and after
- If too many splats were removed (>30% in a single step), warn the user and suggest undo
- If the scene still looks noisy, apply the next operation

### Step 4: Report
- Summarize what was done, how many splats were removed at each step, and the final count

## Auto-Clean Shortcut
For users who just want a quick cleanup, use auto_clean with an appropriate aggressiveness level. Default to "moderate" unless specified.

## Important Notes
- The undo tool can revert each operation individually. Each auto_clean step creates its own undo entry.
- Height values: Y is up. Positive Y = above, negative Y = below. Check the bbox to know the range.
- Color values are [0,1] not [0,255].
- The density filter builds a spatial hash internally — it may take a moment on large scenes.
- Be conservative by default. Better to under-clean than over-clean.
- Always explain what you are doing and why.`

/* -------------------------------------------------------------------------- */
/*  Helpers                                                                   */
/* -------------------------------------------------------------------------- */

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

const rateLimiter = new RateLimiter()

/** Extract function calls from Gemini response parts. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function extractFunctionCalls(parts: any[]): Array<{ name: string; args: Record<string, unknown> }> {
  return parts
    .filter((p) => p?.functionCall)
    .map((p) => ({
      name: p.functionCall.name as string,
      args: (p.functionCall.args ?? {}) as Record<string, unknown>,
    }))
}

/** Extract concatenated text from Gemini response parts. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function extractText(parts: any[]): string {
  return parts
    .filter((p) => typeof p?.text === 'string')
    .map((p) => p.text as string)
    .join('\n')
}

/* -------------------------------------------------------------------------- */
/*  Tool execution                                                            */
/* -------------------------------------------------------------------------- */

/**
 * Execute a single tool call against the ViewerHandle.
 * Returns an API-agnostic result: { text, image?, finalAnswer? }
 */
async function executeTool(
  toolName: string,
  input: Record<string, unknown>,
  viewer: ViewerHandle,
  onAction: (action: AgentAction) => void,
): Promise<ToolExecResult> {
  switch (toolName) {
    /* ---- Camera tools ---- */

    case 'look_at': {
      const { x, y, z } = input as { x: number; y: number; z: number }
      viewer.lookAt(new THREE.Vector3(x, y, z), true)
      onAction({
        type: 'camera_move',
        label: 'Look At',
        detail: `(${x.toFixed(2)}, ${y.toFixed(2)}, ${z.toFixed(2)})`,
      })
      await delay(600)
      return { text: `Camera is now looking at (${x}, ${y}, ${z}).` }
    }

    case 'set_view': {
      const { preset } = input as { preset: 'front' | 'back' | 'top' | 'right' | 'left' | 'iso' }
      viewer.setView(preset, true)
      onAction({ type: 'camera_move', label: 'Set View', detail: preset })
      await delay(600)
      return { text: `Camera set to ${preset} view.` }
    }

    case 'orbit': {
      const { dx, dy } = input as { dx: number; dy: number }
      viewer.orbit(dx, dy)
      onAction({ type: 'camera_move', label: 'Orbit', detail: `dx=${dx}°, dy=${dy}°` })
      return { text: `Orbited camera by dx=${dx}°, dy=${dy}°.` }
    }

    case 'dolly': {
      const { amount } = input as { amount: number }
      viewer.dolly(amount)
      onAction({
        type: 'camera_move',
        label: 'Dolly',
        detail: `${amount > 0 ? '+' : ''}${amount}`,
      })
      return { text: `Dollied camera by ${amount}.` }
    }

    /* ---- Capture ---- */

    case 'capture_frame': {
      const dataUrl = await viewer.captureFrame()
      const base64 = dataUrl.replace(/^data:image\/\w+;base64,/, '')
      onAction({ type: 'capture', label: 'Capture Frame' })
      return { text: 'Frame captured.', image: base64 }
    }

    /* ---- Cleanup tools ---- */

    case 'clean_opacity': {
      const { threshold } = input as { threshold: number }
      const removed = viewer.cleanOpacity(threshold)
      onAction({
        type: 'cleanup',
        label: 'Clean Opacity',
        detail: `threshold=${threshold}`,
        removedCount: removed,
      })
      return {
        text: `Removed ${removed} splats with opacity below ${threshold}. ${viewer.getSplatCount()} splats remaining.`,
      }
    }

    case 'remove_outliers': {
      const { k } = input as { k: number }
      const removed = viewer.removeOutliers(k)
      onAction({
        type: 'cleanup',
        label: 'Remove Outliers',
        detail: `k=${k} std devs`,
        removedCount: removed,
      })
      return {
        text: `Removed ${removed} outlier splats (>${k} std devs from mean). ${viewer.getSplatCount()} splats remaining.`,
      }
    }

    case 'crop_bbox': {
      const { min_x, min_y, min_z, max_x, max_y, max_z } = input as {
        min_x: number
        min_y: number
        min_z: number
        max_x: number
        max_y: number
        max_z: number
      }
      const min = new THREE.Vector3(min_x, min_y, min_z)
      const max = new THREE.Vector3(max_x, max_y, max_z)
      const removed = viewer.cropBbox(min, max)
      onAction({
        type: 'cleanup',
        label: 'Crop BBox',
        detail: `[${min_x},${min_y},${min_z}] - [${max_x},${max_y},${max_z}]`,
        removedCount: removed,
      })
      return {
        text: `Cropped to bounding box. Removed ${removed} splats outside the region. ${viewer.getSplatCount()} splats remaining.`,
      }
    }

    /* ---- Advanced cleanup tools ---- */

    case 'get_scene_stats': {
      const stats = viewer.getSceneStats()
      if (!stats) return { text: 'No scene loaded.' }
      onAction({ type: 'capture', label: 'Scene Stats' })
      const lines = [
        `Splat count: ${stats.count}`,
        `Bounding box: [${stats.bbox.min.x.toFixed(2)}, ${stats.bbox.min.y.toFixed(2)}, ${stats.bbox.min.z.toFixed(2)}] to [${stats.bbox.max.x.toFixed(2)}, ${stats.bbox.max.y.toFixed(2)}, ${stats.bbox.max.z.toFixed(2)}]`,
        `Mean position: (${stats.meanPosition.x.toFixed(2)}, ${stats.meanPosition.y.toFixed(2)}, ${stats.meanPosition.z.toFixed(2)})`,
        `Std position: (${stats.stdPosition.x.toFixed(2)}, ${stats.stdPosition.y.toFixed(2)}, ${stats.stdPosition.z.toFixed(2)})`,
        `Opacity distribution: ${stats.opacityHistogram.map((c, i) => `[${(i * 0.1).toFixed(1)}-${((i + 1) * 0.1).toFixed(1)}): ${c}`).join(', ')}`,
        `Scale distribution (log10): range ${stats.scaleHistogram.minLog.toFixed(2)} to ${stats.scaleHistogram.maxLog.toFixed(2)}, buckets: [${stats.scaleHistogram.buckets.join(', ')}]`,
        `Dominant colors: ${stats.dominantColors.map((c) => `rgb(${Math.round(c.r * 255)},${Math.round(c.g * 255)},${Math.round(c.b * 255)}) x${c.count}`).join(', ')}`,
        `Estimated density radius: ${stats.estimatedDensityRadius.toFixed(4)}`,
      ]
      return { text: lines.join('\n') }
    }

    case 'filter_by_scale': {
      const { min_scale, max_scale } = input as { min_scale?: number; max_scale?: number }
      const removed = viewer.filterByScale(min_scale, max_scale)
      onAction({
        type: 'cleanup',
        label: 'Filter by Scale',
        detail: `min=${min_scale ?? 'none'}, max=${max_scale ?? 'none'}`,
        removedCount: removed,
      })
      return {
        text: `Removed ${removed} splats outside scale range. ${viewer.getSplatCount()} remaining.`,
      }
    }

    case 'filter_by_color': {
      const { r, g, b, tolerance } = input as {
        r: number
        g: number
        b: number
        tolerance: number
      }
      const removed = viewer.filterByColor(r, g, b, tolerance)
      onAction({
        type: 'cleanup',
        label: 'Filter by Color',
        detail: `rgb(${Math.round(r * 255)},${Math.round(g * 255)},${Math.round(b * 255)}) tol=${tolerance}`,
        removedCount: removed,
      })
      return {
        text: `Removed ${removed} splats matching target color. ${viewer.getSplatCount()} remaining.`,
      }
    }

    case 'filter_by_density': {
      const { min_neighbors, radius } = input as { min_neighbors: number; radius: number }
      const removed = viewer.filterByDensity(min_neighbors, radius)
      onAction({
        type: 'cleanup',
        label: 'Filter by Density',
        detail: `min_neighbors=${min_neighbors}, radius=${radius.toFixed(4)}`,
        removedCount: removed,
      })
      return {
        text: `Removed ${removed} isolated splats (fewer than ${min_neighbors} neighbors within radius ${radius.toFixed(4)}). ${viewer.getSplatCount()} remaining.`,
      }
    }

    case 'filter_by_height': {
      const { min_y, max_y } = input as { min_y?: number; max_y?: number }
      const removed = viewer.filterByHeight(min_y, max_y)
      onAction({
        type: 'cleanup',
        label: 'Filter by Height',
        detail: `min_y=${min_y ?? 'none'}, max_y=${max_y ?? 'none'}`,
        removedCount: removed,
      })
      return {
        text: `Removed ${removed} splats outside height range. ${viewer.getSplatCount()} remaining.`,
      }
    }

    case 'auto_clean': {
      const { aggressiveness } = input as {
        aggressiveness: 'gentle' | 'moderate' | 'aggressive'
      }
      const stats = viewer.getSceneStats()
      if (!stats) return { text: 'No scene loaded.' }

      const presets = {
        gentle: { opacityThresh: 0.02, minNeighbors: 2, densityMul: 1.0, outlierK: 5 },
        moderate: { opacityThresh: 0.08, minNeighbors: 4, densityMul: 1.0, outlierK: 3.5 },
        aggressive: { opacityThresh: 0.15, minNeighbors: 8, densityMul: 0.8, outlierK: 2.5 },
      }
      const p = presets[aggressiveness]

      // Compute scale cutoff from histogram
      const cutoffPct = { gentle: 0.99, moderate: 0.95, aggressive: 0.9 }
      const totalInHist = stats.scaleHistogram.buckets.reduce((a, b) => a + b, 0)
      const cutoffCount = totalInHist * cutoffPct[aggressiveness]
      let cumulative = 0,
        cutoffBucket = 9
      for (let i = 0; i < 10; i++) {
        cumulative += stats.scaleHistogram.buckets[i]
        if (cumulative >= cutoffCount) {
          cutoffBucket = i
          break
        }
      }
      const scaleRange = stats.scaleHistogram.maxLog - stats.scaleHistogram.minLog
      const maxScale = Math.pow(
        10,
        stats.scaleHistogram.minLog + ((cutoffBucket + 1) / 10) * scaleRange,
      )
      const densityRadius = stats.estimatedDensityRadius * p.densityMul

      let totalRemoved = 0
      const steps: string[] = []

      const r1 = viewer.cleanOpacity(p.opacityThresh)
      totalRemoved += r1
      steps.push(`Opacity (threshold=${p.opacityThresh}): -${r1}`)

      const r2 = viewer.filterByScale(undefined, maxScale)
      totalRemoved += r2
      steps.push(`Scale (max=${maxScale.toFixed(4)}): -${r2}`)

      const r3 = viewer.filterByDensity(p.minNeighbors, densityRadius)
      totalRemoved += r3
      steps.push(`Density (min_neighbors=${p.minNeighbors}, radius=${densityRadius.toFixed(4)}): -${r3}`)

      const r4 = viewer.removeOutliers(p.outlierK)
      totalRemoved += r4
      steps.push(`Outliers (k=${p.outlierK}): -${r4}`)

      onAction({
        type: 'cleanup',
        label: 'Auto Clean',
        detail: `${aggressiveness}: -${totalRemoved} total`,
        removedCount: totalRemoved,
      })
      return {
        text: `Auto-clean (${aggressiveness}) complete. Removed ${totalRemoved} splats total.\n${steps.join('\n')}\n${viewer.getSplatCount()} splats remaining.`,
      }
    }

    case 'undo': {
      const success = viewer.undo()
      onAction({
        type: 'cleanup',
        label: 'Undo',
        detail: success ? 'Reverted last operation' : 'Nothing to undo',
      })
      return {
        text: success
          ? `Undo successful. ${viewer.getSplatCount()} splats restored.`
          : 'Nothing to undo.',
      }
    }

    /* ---- Answer ---- */

    case 'answer': {
      const { text } = input as { text: string }
      onAction({ type: 'answer', label: 'Answer', detail: text })
      return { text: 'Answer delivered.', finalAnswer: text }
    }

    default:
      return { text: `Unknown tool: ${toolName}` }
  }
}

/* -------------------------------------------------------------------------- */
/*  Main agent loop                                                           */
/* -------------------------------------------------------------------------- */

/**
 * Run the agentic tool-use loop using Gemini Flash.
 *
 * Sends a user message, then iteratively executes any requested tool calls
 * until the model stops or we hit maxSteps.
 *
 * @returns The final assistant text answer.
 */
export async function runAgentLoop(
  userMessage: string,
  conversationHistory: unknown[],
  viewer: ViewerHandle,
  config: AgentConfig,
  onAction: (action: AgentAction) => void,
  onThinking: (thinking: boolean) => void,
  signal?: AbortSignal,
): Promise<string> {
  const apiKey = import.meta.env.VITE_GEMINI_API_KEY as string | undefined
  if (!apiKey) {
    throw new Error('Missing VITE_GEMINI_API_KEY environment variable.')
  }

  const genAI = new GoogleGenerativeAI(apiKey)
  const model = genAI.getGenerativeModel({
    model: config.model,
    systemInstruction: SYSTEM_PROMPT,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    tools: [{ functionDeclarations: AGENT_TOOLS as any }],
    generationConfig: { maxOutputTokens: 4096 },
  })

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chat = model.startChat({ history: conversationHistory as any })

  let steps = 0
  let finalAnswer = ''

  onThinking(true)

  try {
    // --- Initial user message ---
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')

    await rateLimiter.acquire()
    const t0 = performance.now()
    let result = await withRetry(() => chat.sendMessage(userMessage))
    steps++
    console.log(
      `[AGENT step=${steps}] → model (${((performance.now() - t0) / 1000).toFixed(1)}s)`,
    )

    // --- Tool-use loop ---
    while (steps < config.maxSteps) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')

      const candidates = result.response.candidates
      if (!candidates || candidates.length === 0) {
        // Safety block or empty response
        const feedback = result.response.promptFeedback
        const reason = feedback
          ? `Blocked: ${JSON.stringify(feedback)}`
          : 'No response from model.'
        finalAnswer = reason
        break
      }

      const parts = candidates[0].content?.parts ?? []
      const funcCalls = extractFunctionCalls(parts)

      // If no function calls, the model is done — extract text.
      if (funcCalls.length === 0) {
        finalAnswer = extractText(parts)
        break
      }

      // Execute each tool and collect function responses + images separately.
      // Gemini forbids mixing functionResponse with other part types in one message.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const funcResponseParts: any[] = []
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const imageParts: any[] = []

      for (const call of funcCalls) {
        if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')

        console.log(
          `[AGENT step=${steps}] Exec: ${call.name}(${JSON.stringify(call.args).slice(0, 80)})`,
        )

        const execResult = await executeTool(call.name, call.args, viewer, onAction)

        funcResponseParts.push({
          functionResponse: {
            name: call.name,
            response: { result: execResult.text },
          },
        })

        if (execResult.image) {
          imageParts.push({
            inlineData: {
              mimeType: 'image/jpeg',
              data: execResult.image,
            },
          })
        }

        if (execResult.finalAnswer !== undefined) {
          finalAnswer = execResult.finalAnswer
        }

        await delay(200)
      }

      // If the answer tool was invoked, we're done.
      if (finalAnswer) break

      // Send function responses (must be alone — no other part types).
      await rateLimiter.acquire()
      const t1 = performance.now()
      result = await withRetry(() => chat.sendMessage(funcResponseParts))
      steps++
      console.log(
        `[AGENT step=${steps}] → model (${((performance.now() - t1) / 1000).toFixed(1)}s), ${funcResponseParts.length} func responses`,
      )

      // If tools captured images, send them as a follow-up user message
      // so the model can actually "see" the frames.
      if (imageParts.length > 0 && steps < config.maxSteps) {
        await rateLimiter.acquire()
        const t2 = performance.now()
        result = await withRetry(() =>
          chat.sendMessage([
            { text: 'Here are the captured frame(s) from the tools above. Analyze what you see:' },
            ...imageParts,
          ]),
        )
        steps++
        console.log(
          `[AGENT step=${steps}] → model with ${imageParts.length} image(s) (${((performance.now() - t2) / 1000).toFixed(1)}s)`,
        )
      }
    }
  } finally {
    onThinking(false)
  }

  if (!finalAnswer) {
    finalAnswer =
      'I reached the maximum number of steps without arriving at a final answer. Please try again with a more specific request.'
  }

  return finalAnswer
}
