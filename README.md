# GeoSplat Inspector

A browser-based viewer for Gaussian splats of real-world scenes (UAV
captures, handheld scans, drone footage) where you can talk to the scene
and have a Claude agent fly the camera, look around, and answer questions
about what it sees.

## Repo layout

- `pipeline/` — Python pipeline that runs on Jetstream. Takes a video and
  produces a trained `.ply` Gaussian splat.
- `viewer/` — Next.js + TypeScript app that renders splats in the browser
  and hosts the agent loop.
- `docs/` — Project documentation and phase plans.
- `.claude/skills/` — Project-scoped Claude Code skills.

## Getting started

Read [`docs/00-start-here.md`](docs/00-start-here.md) end to end. It walks
through the architecture, what to install, the project's Claude Code
configuration, and Phase 0 + Phase 1 setup.

## Status

Phase 0 in progress.
