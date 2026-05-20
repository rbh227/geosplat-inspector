---
name: geosplat-viewer
description: Use when working on the viewer Next.js app (anything in viewer/). Triggers on "add a tool", "agent loop", "new viewer feature", "tool schema", "splat renderer", or any reference to the chat/camera/render functionality. Also use when debugging the Anthropic SDK integration or the agent's tool calls.
---

# GeoSplat viewer

## Stack

- Next.js 14+ App Router, TypeScript
- Splat renderer: forked from antimatter15/splat (WebGL) initially
- Anthropic SDK for the agent loop
- Tailwind v4 + shadcn/ui for chat UI components

## Project structure

```
viewer/
├── src/
│   ├── app/                  # Next.js routes
│   ├── components/
│   │   ├── SplatViewer.tsx   # the canvas + camera control
│   │   ├── ChatPanel.tsx     # the right-side chat UI
│   │   └── ui/               # shadcn primitives
│   ├── lib/
│   │   ├── viewer-api.ts     # JS functions exposed to the agent
│   │   ├── tools.ts          # Anthropic tool schemas
│   │   └── agent.ts          # the agent loop
│   └── app/
│       └── api/
│           └── chat/route.ts # serverless relay to Anthropic
```

## Tool conventions

Every viewer-controllable function lives in `lib/viewer-api.ts` and is
mirrored by an Anthropic tool schema in `lib/tools.ts`. Adding a new agent
capability means: implement the function, add the schema, add the dispatch
in the agent loop.

## Agent loop sketch

1. User message → send to /api/chat with history
2. Anthropic responds with text + tool_use blocks
3. For each tool_use: dispatch to viewer-api, capture result (including
   screenshot if applicable)
4. Send tool results back to Anthropic with continued history
5. Loop until response has no more tool_use blocks
6. Stream final text to chat panel

## Notes

- Screenshots are sent to Anthropic as base64 PNG image blocks. Target
  ~768px square — large enough for Claude's vision, small enough to keep
  token costs sane.
- API key in `.env.local` as `ANTHROPIC_API_KEY`. Server-side only.
- The agent system prompt is in `lib/agent.ts`. Iterate on it after
  watching the agent fail a few times — not before.
