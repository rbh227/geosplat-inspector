import type { ToolName } from '../types/agent'

export type { ToolName }

/**
 * Tool input types — discriminated union keyed on tool name.
 * Used internally by executeTool() for type narrowing.
 */
export type ToolInput =
  | { name: 'look_at'; input: { x: number; y: number; z: number } }
  | { name: 'set_view'; input: { preset: 'front' | 'back' | 'top' | 'right' | 'left' | 'iso' } }
  | { name: 'orbit'; input: { dx: number; dy: number } }
  | { name: 'dolly'; input: { amount: number } }
  | { name: 'capture_frame'; input: Record<string, never> }
  | { name: 'clean_opacity'; input: { threshold: number } }
  | { name: 'remove_outliers'; input: { k: number } }
  | { name: 'crop_bbox'; input: { min_x: number; min_y: number; min_z: number; max_x: number; max_y: number; max_z: number } }
  | { name: 'get_scene_stats'; input: Record<string, never> }
  | { name: 'filter_by_scale'; input: { min_scale?: number; max_scale?: number } }
  | { name: 'filter_by_color'; input: { r: number; g: number; b: number; tolerance: number } }
  | { name: 'filter_by_density'; input: { min_neighbors: number; radius: number } }
  | { name: 'filter_by_height'; input: { min_y?: number; max_y?: number } }
  | { name: 'auto_clean'; input: { aggressiveness: 'gentle' | 'moderate' | 'aggressive' } }
  | { name: 'undo'; input: Record<string, never> }
  | { name: 'answer'; input: { text: string } }

/**
 * Gemini function declarations for agent tools.
 * Schema type strings match the Gemini API ('OBJECT', 'NUMBER', 'STRING').
 * Cast to `any` when passing to getGenerativeModel() if TypeScript complains
 * about enum vs string literal mismatch.
 */
export const AGENT_TOOLS = [
  {
    name: 'look_at',
    description: 'Point the camera at a specific 3D point in the scene',
    parameters: {
      type: 'OBJECT',
      properties: {
        x: { type: 'NUMBER', description: 'X coordinate' },
        y: { type: 'NUMBER', description: 'Y coordinate' },
        z: { type: 'NUMBER', description: 'Z coordinate' },
      },
      required: ['x', 'y', 'z'],
    },
  },
  {
    name: 'set_view',
    description: 'Set camera to a preset view angle',
    parameters: {
      type: 'OBJECT',
      properties: {
        preset: {
          type: 'STRING',
          enum: ['front', 'back', 'top', 'right', 'left', 'iso'],
          description: 'View preset',
        },
      },
      required: ['preset'],
    },
  },
  {
    name: 'orbit',
    description:
      'Orbit the camera relative to current position. dx rotates horizontally (degrees), dy rotates vertically (degrees).',
    parameters: {
      type: 'OBJECT',
      properties: {
        dx: { type: 'NUMBER', description: 'Horizontal rotation in degrees' },
        dy: { type: 'NUMBER', description: 'Vertical rotation in degrees' },
      },
      required: ['dx', 'dy'],
    },
  },
  {
    name: 'dolly',
    description: 'Move camera closer (negative) or further (positive) from the target',
    parameters: {
      type: 'OBJECT',
      properties: {
        amount: {
          type: 'NUMBER',
          description: 'Dolly amount (negative = closer, positive = further)',
        },
      },
      required: ['amount'],
    },
  },
  {
    name: 'capture_frame',
    description:
      'Capture the current view as an image to analyze the scene. Always call this after moving the camera to see the result.',
    parameters: {
      type: 'OBJECT',
      properties: {},
    },
  },
  {
    name: 'clean_opacity',
    description: 'Remove splats with opacity below a threshold. Good for cleaning semi-transparent floaters.',
    parameters: {
      type: 'OBJECT',
      properties: {
        threshold: {
          type: 'NUMBER',
          description: 'Opacity threshold (0-1). Splats below this are removed. Typical: 0.05-0.2',
        },
      },
      required: ['threshold'],
    },
  },
  {
    name: 'remove_outliers',
    description: 'Remove spatially outlier splats that are far from the main cluster of points',
    parameters: {
      type: 'OBJECT',
      properties: {
        k: {
          type: 'NUMBER',
          description:
            'Number of standard deviations. Splats further than k*std from mean are removed. Typical: 2-5',
        },
      },
      required: ['k'],
    },
  },
  {
    name: 'crop_bbox',
    description: 'Keep only splats within a 3D bounding box, removing everything outside',
    parameters: {
      type: 'OBJECT',
      properties: {
        min_x: { type: 'NUMBER' },
        min_y: { type: 'NUMBER' },
        min_z: { type: 'NUMBER' },
        max_x: { type: 'NUMBER' },
        max_y: { type: 'NUMBER' },
        max_z: { type: 'NUMBER' },
      },
      required: ['min_x', 'min_y', 'min_z', 'max_x', 'max_y', 'max_z'],
    },
  },
  {
    name: 'get_scene_stats',
    description:
      'Get detailed statistics about the current splat scene: splat count, bounding box, ' +
      'position distribution, opacity histogram, scale distribution, dominant colors, and ' +
      'estimated density radius. Call this BEFORE cleanup to understand the data and choose parameters.',
    parameters: {
      type: 'OBJECT',
      properties: {},
    },
  },
  {
    name: 'filter_by_scale',
    description:
      'Remove splats whose maximum axis scale is outside the given range. ' +
      'Useful for removing oversized "blob" splats (set max_scale) or tiny imperceptible splats (set min_scale). ' +
      'Check get_scene_stats first to see the scale distribution.',
    parameters: {
      type: 'OBJECT',
      properties: {
        min_scale: { type: 'NUMBER', description: 'Minimum allowed scale. Optional.' },
        max_scale: { type: 'NUMBER', description: 'Maximum allowed scale. Typical: 0.01-0.5' },
      },
    },
  },
  {
    name: 'filter_by_color',
    description:
      'Remove splats that match a target color within a tolerance in HSL color space. ' +
      'Useful for removing sky artifacts (target: light blue, r=0.53 g=0.81 b=0.98) ' +
      'or specific colored noise. Colors are in [0,1] range (not 0-255).',
    parameters: {
      type: 'OBJECT',
      properties: {
        r: { type: 'NUMBER', description: 'Target red [0-1]' },
        g: { type: 'NUMBER', description: 'Target green [0-1]' },
        b: { type: 'NUMBER', description: 'Target blue [0-1]' },
        tolerance: { type: 'NUMBER', description: 'HSL distance tolerance [0-1]. Lower = more selective. Typical: 0.1-0.3' },
      },
      required: ['r', 'g', 'b', 'tolerance'],
    },
  },
  {
    name: 'filter_by_density',
    description:
      'Remove isolated "floater" splats that have fewer than min_neighbors within radius distance. ' +
      'This is the most effective tool for cleaning scattered noise in aerial/drone scenes. ' +
      'Use get_scene_stats to get the estimated_density_radius as a starting radius. ' +
      'Typical: min_neighbors=3-10, radius from stats.',
    parameters: {
      type: 'OBJECT',
      properties: {
        min_neighbors: { type: 'NUMBER', description: 'Minimum neighbors required to keep a splat. Typical: 3-10' },
        radius: { type: 'NUMBER', description: 'Search radius for counting neighbors. Use estimated_density_radius from get_scene_stats.' },
      },
      required: ['min_neighbors', 'radius'],
    },
  },
  {
    name: 'filter_by_height',
    description:
      'Remove splats outside a Y-axis height range. Y-axis is up in the viewer. ' +
      'Useful for removing sky artifacts (set max_y) or underground noise (set min_y). ' +
      'Check bbox from get_scene_stats to know the Y range.',
    parameters: {
      type: 'OBJECT',
      properties: {
        min_y: { type: 'NUMBER', description: 'Minimum Y (splats below removed). Optional.' },
        max_y: { type: 'NUMBER', description: 'Maximum Y (splats above removed). Optional.' },
      },
    },
  },
  {
    name: 'auto_clean',
    description:
      'Run an automated multi-step cleanup pipeline: opacity -> scale -> density -> outlier. ' +
      'Three aggressiveness levels with data-driven parameters. Always capture_frame after to verify.',
    parameters: {
      type: 'OBJECT',
      properties: {
        aggressiveness: {
          type: 'STRING',
          enum: ['gentle', 'moderate', 'aggressive'],
          description: 'gentle: conservative. moderate: balanced. aggressive: maximum cleanup.',
        },
      },
      required: ['aggressiveness'],
    },
  },
  {
    name: 'undo',
    description: 'Undo the last cleanup operation. Can be called multiple times.',
    parameters: {
      type: 'OBJECT',
      properties: {},
    },
  },
  {
    name: 'answer',
    description: 'Provide a final answer to the user. Call this when you have enough information to respond.',
    parameters: {
      type: 'OBJECT',
      properties: {
        text: { type: 'STRING', description: 'The answer text' },
      },
      required: ['text'],
    },
  },
]
