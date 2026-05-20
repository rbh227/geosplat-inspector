# GeoSplat Inspector — Start Here

This is the single document you need to begin the project. Everything — repo
structure, Claude Code config, the skills to install, the first three phases
of work — is in here.

How to use this file:
1. Read sections 1 and 2 once to get oriented.
2. Work through Phase 0 (section 5) start to finish.
3. When Phase 0 is done, do Phase 1 (section 6).
4. Each section has a "Definition of done" — don't move on until it's met.

---

## 1. Project context

A browser-based viewer for Gaussian splats of real-world scenes — UAV
captures, handheld scans, drone footage — where you can talk to the scene
and have an LLM agent fly the camera, look around, and answer questions
about what it sees.

### What it is

You upload a video. The pipeline turns it into a 3D Gaussian splat — a
photorealistic 3D representation that renders in real-time in a browser.
Then you open the scene in a chat-enabled viewer: type a question, and a
Claude agent moves the virtual camera around the scene, takes screenshots,
reasons over them, and answers.

Example interactions the agent should eventually handle:
- "Show me the back of the building."
- "Find the most damaged structure on this block."
- "How tall is that tree compared to the roof next to it?"
- "Walk me through this room and describe what you see."

### Why this is interesting

Splat viewers exist. Chat interfaces to images exist. An agent that
*navigates* a photorealistic 3D scene and reasons over its own rendered
views — that's new ground. The interaction model is "vision-mediated
agency": Claude doesn't see the scene directly, it sees what the virtual
camera renders, just like a human looking through a viewport.

The project sits at the intersection of UAV imagery, agentic LLM tooling,
computer vision, and web tech — without overlapping the existing day-job
lanes (Bina Lab 2D damage segmentation, Clearline Terminal for prediction
markets).

### Architecture, at a glance

- **Pipeline** (Python, runs on Jetstream GPU): video → frames → camera
  poses (COLMAP) → trained Gaussian splat (.ply). One-time per scene.
  Compute lives here only when training; instance is shelved otherwise.

- **Viewer** (TypeScript + Next.js, runs in browser + Vercel): renders .ply
  files via WebGL/WebGPU. Hosts the agent loop. The Anthropic API is called
  from a serverless function on Vercel; no GPU runtime needed at serving.

- **Splat files** are static assets — hosted on Vercel Blob, Supabase
  Storage, or similar. The 3D model lives at a URL like any image.

### Stack at a glance

| Layer | Tool |
|---|---|
| Pose estimation | COLMAP (via nerfstudio's `ns-process-data`) |
| Splat training | gsplat (via nerfstudio's `splatfacto`) |
| Splat viewer | Fork of `antimatter15/splat` (WebGL, ~1000 LOC) |
| Frontend | Next.js 14 App Router, TypeScript |
| Agent | Anthropic SDK, direct API calls via serverless route |
| Hosting | Vercel (viewer + relay), Vercel Blob (splats), Jetstream (training only) |

### Scenes

The first goal is to make the pipeline work on easy scenes (a building, a
sculpture, a room). The real payoff is aerial UAV scenes from Hurricane Ian,
where the project becomes a portfolio piece and a possible research lead in
agentic damage assessment.

---

## 2. What you need installed

### On your laptop (do this first)

- **Node.js 20+** — `brew install node` on Mac, or nvm
- **Git + the `gh` CLI** — `brew install gh` then `gh auth login`
- **VS Code with the Claude Code extension** — already done
- **A modern Chrome or Edge** — for WebGPU testing
- **SSH config pointing at Jetstream** — already set up from Bina work

### On Jetstream (Phase 0 sets this up)

- Conda env named `geosplat`
- PyTorch 2.1.2 with CUDA 12.1
- nerfstudio (pulls in gsplat, viser, and the rest)
- `ffmpeg` for video → frames

---

## 3. Claude Code skills to install before you start

I researched what's actually in the popular skill repos. Don't install the
whole `mattpocock/skills` collection — most of it is generic engineering
discipline you don't need for this project. Cherry-pick a few that earn
their slot.

### From `mattpocock/skills`

The repo lives at https://github.com/mattpocock/skills. Three skills from
it are worth grabbing as personal skills (in `~/.claude/skills/`):

1. **`grill-me`** — forces the agent to ask clarifying questions before
   writing code, when you give a vague request. Catches misalignment early.
2. **`diagnose`** — disciplined debugging loop (reproduce → minimise →
   hypothesise → instrument → fix). Useful when COLMAP or gsplat fails in
   ways that aren't obvious.
3. **`tdd`** — red-green-refactor for the viewer code. Only use this for
   the TypeScript/Next.js side; the pipeline scripts don't need TDD.

Skip everything else from that repo. The "engineering" suite (`to-prd`,
`to-issues`, `triage`, `improve-codebase-architecture`) is built around a
team workflow with a ticket tracker. Overkill for a one-person personal
project.

To install one of these, clone the repo, copy the SKILL.md and any
supporting files into your `~/.claude/skills/<skill-name>/` folder. Don't
install the whole repo via the plugin marketplace — that drags in 20+
skills you'll never use.

### From other authors

Two skills outside Pocock's repo that are directly relevant:

4. **`frontend-design`** — Anthropic's own skill (in the
   `anthropics/skills` repo under `skills/`). Forces Claude to make bold
   design decisions instead of producing generic AI-aesthetic React
   components. Install before you build the viewer UI.

5. **`tailwind-v4-shadcn`** from `secondsky/claude-skills` — production-
   tested setup recipe for Tailwind v4 + shadcn/ui + Vite/React. Covers
   the @theme inline pattern, CSS variables, dark mode, and the gotchas
   that come up when you mix v4 and shadcn. Will save you debugging time
   when scaffolding the viewer.

### Project-scoped skills (lives in repo, set up in Phase 0)

These two are in the repo at `.claude/skills/`, committed to git, so they
follow the code to any machine including Jetstream:

6. **`splat-pipeline`** — codifies the training pipeline commands, common
   failures, and data layout. The full contents are in section 4 below.

7. **`geosplat-viewer`** — codifies the viewer architecture and the
   conventions for adding new agent tools. Full contents in section 4.

### Personal skill (laptop only, not in repo)

8. **`jetstream-session`** — your SSH details, env activation, volume
   location. Lives in `~/.claude/skills/`. Full contents in section 4.

### How to verify they're loaded

In Claude Code, type `/` and you should see your skills appear as slash
commands. If a skill doesn't show up, either the description's trigger
phrases need to be more explicit, or you put it in the wrong directory.

---

## 4. Files to create

Below are the exact contents of every file you need to scaffold. Paste them
as-is; edit only the SSH IP and any names if I guessed wrong.

### 4.1 `CLAUDE.md` (repo root)

See [../CLAUDE.md](../CLAUDE.md) in this repo for the live copy.

### 4.2 `.gitignore` (repo root)

See [../.gitignore](../.gitignore) in this repo for the live copy.

### 4.3 `.claude/skills/splat-pipeline/SKILL.md`

See [../.claude/skills/splat-pipeline/SKILL.md](../.claude/skills/splat-pipeline/SKILL.md) for the live copy.

### 4.4 `.claude/skills/geosplat-viewer/SKILL.md`

See [../.claude/skills/geosplat-viewer/SKILL.md](../.claude/skills/geosplat-viewer/SKILL.md) for the live copy.

### 4.5 `~/.claude/skills/jetstream-session/SKILL.md` (personal, laptop only)

This one lives outside the repo. Content reference:

```markdown
---
name: jetstream-session
description: Use when the user mentions Jetstream, exouser, the Tene_Volume, or wants to run experiments on the remote GPU box. Triggers on "ssh in", "set up the env", "run on jetstream", "check the volume", or any time the work needs a GPU that the local machine lacks.
---

# Jetstream session

## Connect

ssh exouser@149.165.173.161

## Persistent volume

/media/volume/Tene_Volume/ — survives shelving. All project code, data,
and conda envs live here.

## Standard project setup for GeoSplat

cd /media/volume/Tene_Volume/geosplat-inspector/pipeline
conda activate geosplat
nvidia-smi
df -h /media/volume/Tene_Volume

## Shelving etiquette

When done with a session:
- Sync .ply outputs back to laptop or to Vercel Blob
- Commit and push any code changes
- Shelve via the Jetstream web UI (not from the terminal)
```

---

## 5. Phase 0 — Setup

**Goal:** every tool and environment is ready, the repo is structured,
Claude Code knows the project, and a single test command on Jetstream
proves the GPU pipeline works. No splats trained yet, no viewer code
written yet.

**Definition of done:** You can SSH into Jetstream, activate the `geosplat`
conda env, and run `ns-train --help` plus
`python -c "import torch; print(torch.cuda.is_available())"` successfully.
Repo is pushed to GitHub with CLAUDE.md, skills, and phase docs in place.

**Estimated time:** 1.5–2 hours, mostly waiting for pip installs.

### Checklist

#### Local repo setup

- [ ] `mkdir geosplat-inspector && cd geosplat-inspector`
- [ ] `git init`
- [ ] `gh repo create geosplat-inspector --public --source=. --remote=origin`
  (or create on github.com manually and `git remote add origin <url>`)
- [ ] Create folder structure:
  ```
  mkdir -p pipeline/scripts pipeline/data viewer docs .claude/skills/splat-pipeline .claude/skills/geosplat-viewer
  ```
- [ ] Create top-level files: `CLAUDE.md`, `README.md`, `.gitignore`
- [ ] Paste contents from section 4.1 into `CLAUDE.md`
- [ ] Paste contents from section 4.2 into `.gitignore`
- [ ] Paste contents from section 4.3 into
      `.claude/skills/splat-pipeline/SKILL.md`
- [ ] Paste contents from section 4.4 into
      `.claude/skills/geosplat-viewer/SKILL.md`
- [ ] Save this file as `docs/00-start-here.md` so future-you can find it

#### Personal skills (laptop only)

- [ ] `mkdir -p ~/.claude/skills/jetstream-session`
- [ ] Paste contents from section 4.5 into
      `~/.claude/skills/jetstream-session/SKILL.md`
- [ ] (Optional) Clone `mattpocock/skills`, copy the `grill-me`,
      `diagnose`, and `tdd` skills into `~/.claude/skills/`
- [ ] (Optional) Install the `frontend-design` skill from
      `anthropics/skills` into `~/.claude/skills/`
- [ ] (Optional) Install `tailwind-v4-shadcn` from `secondsky/claude-skills`
      into `~/.claude/skills/`

#### Verify Claude Code knows the project

- [ ] Open VS Code at the repo root locally
- [ ] Open Claude Code, ask: "What's this project and where does training
      run?"
- [ ] Expected: Claude summarizes the architecture from CLAUDE.md,
      mentions Jetstream
- [ ] Type `/` in Claude Code, confirm `/splat-pipeline`,
      `/geosplat-viewer`, `/jetstream-session` appear as slash commands

#### First commit

- [ ] `git add . && git commit -m "Phase 0: scaffold, skills, phase docs"`
- [ ] `git push -u origin main`

#### Jetstream environment

- [ ] SSH into Jetstream: `ssh exouser@149.165.173.161`
- [ ] `cd /media/volume/Tene_Volume`
- [ ] `git clone https://github.com/<you>/geosplat-inspector.git`
- [ ] `cd geosplat-inspector`
- [ ] Create conda env:
  ```
  conda create -n geosplat python=3.11 -y
  conda activate geosplat
  ```
- [ ] Install PyTorch (CUDA 12.1 build):
  ```
  pip install torch==2.1.2 torchvision==0.16.2 --index-url https://download.pytorch.org/whl/cu121
  ```
- [ ] Install nerfstudio (~10 min):
  ```
  pip install nerfstudio
  ```
- [ ] Confirm GPU access:
  ```
  python -c "import torch; print(torch.cuda.is_available(), torch.cuda.device_count())"
  # Expected: True 4
  ```
- [ ] Confirm CLI tools:
  ```
  ns-train --help
  ns-process-data --help
  ns-export --help
  ```

### What's NOT in this phase

- No video has been recorded yet
- No splat has been trained
- No viewer code exists
- No Anthropic API calls
- No Vercel deploy

### If you get stuck

- **nerfstudio install fails on PyTorch version mismatch:** the most common
  failure. Make sure the cu121 PyTorch wheel installed before nerfstudio.
  If not, uninstall both and reinstall in order.
- **`torch.cuda.is_available()` returns False:** check `nvidia-smi` from
  the shell. If that works but Python doesn't see CUDA, you installed the
  CPU-only PyTorch by accident. Reinstall with the `--index-url` flag above.
- **`ns-train --help` errors on import:** usually a `gsplat` CUDA build
  issue. Try `pip install gsplat --no-build-isolation` to force rebuild.
- **`gh repo create` fails:** make sure you ran `gh auth login` and have a
  GitHub account with available repo names.

Once all checklist items are green, move to Phase 1 below.

---

## 6. Phase 1 — First splat, rendered locally

**Goal:** train a Gaussian splat from a phone video, get it rendering in
Chrome on `localhost`. No agent. No chat. No deploy. Just: video in, 3D
scene out, viewable in a browser tab.

**Definition of done:** You can open `localhost:8000` (or whatever port the
viewer uses) in Chrome and orbit a Gaussian splat of a real scene you
scanned. The framerate is smooth (60+ fps for a small scene).

**Estimated time:** 2–4 hours, mostly hands-off (COLMAP + training run in
the background).

### Checklist

#### Record the source video

- [ ] Pick an easy subject for the first scene: a statue, a sculpture, a
      parked car with stuff around it, the entrance to a building.
      Outdoor preferred (good lighting, no glass/mirrors).
- [ ] Record 30–60 seconds of slow, steady walking around the subject.
- [ ] Aim for ~70% overlap between consecutive frames (move slowly).
- [ ] Vary height slightly partway through — circle at chest height,
      then a shorter circle at waist or above-head height.
- [ ] Settings: 1080p, 30fps, HDR off, Cinematic mode off,
      stabilization on.

#### Upload to Jetstream

- [ ] From your laptop:
  ```
  scp scene1.mp4 exouser@149.165.173.161:/media/volume/Tene_Volume/geosplat-inspector/pipeline/data/raw/scene1.mp4
  ```

#### Run the pipeline

On Jetstream, in
`/media/volume/Tene_Volume/geosplat-inspector/pipeline`:

- [ ] **Extract frames**:
  ```
  mkdir -p data/frames/scene1 data/colmap data/splats
  ffmpeg -i data/raw/scene1.mp4 -vf fps=5 data/frames/scene1/%04d.jpg
  ```
  Confirm: `ls data/frames/scene1/ | wc -l` returns 150–300.

- [ ] **Run COLMAP via nerfstudio**:
  ```
  ns-process-data images --data data/frames/scene1 --output-dir data/colmap/scene1
  ```
  Watch for: "registered N images". N should be ≥ 90% of frame count.
  Expected time: 5–20 min.

- [ ] **Train the splat**:
  ```
  ns-train splatfacto --data data/colmap/scene1 \
      --output-dir data/splats/scene1 \
      --max-num-iterations 30000
  ```
  Watch PSNR climbing. Should pass 25 by iteration 5000, 30+ by the end
  for a clean scene. Expected time: 20–45 min on one L40.

- [ ] **Export .ply**: find the config file path printed at the end of
      training (something like
      `data/splats/scene1/.../config.yml`), then:
  ```
  ns-export gaussian-splat \
      --load-config data/splats/scene1/<run_id>/config.yml \
      --output-dir data/splats/scene1
  ```
  Confirm: `data/splats/scene1/splat.ply` exists, 50–500 MB.

#### Get the .ply onto your laptop

- [ ] From laptop:
  ```
  mkdir -p ~/geosplat-local
  scp exouser@149.165.173.161:/media/volume/Tene_Volume/geosplat-inspector/pipeline/data/splats/scene1/splat.ply ~/geosplat-local/scene1.ply
  ```

#### Set up the local viewer

- [ ] Clone the upstream viewer:
  ```
  cd ~/code  # or wherever you keep projects
  git clone https://github.com/antimatter15/splat geosplat-viewer-vendor
  cd geosplat-viewer-vendor
  ```
- [ ] Copy your `.ply` into the project's static directory (location
      depends on the fork — for `antimatter15/splat`, drop it next to
      `index.html`).
- [ ] Edit the hardcoded URL in `main.js` (or wherever the splat URL is
      set) to point at your local file.
- [ ] Serve the directory:
  ```
  python3 -m http.server 8000
  ```
- [ ] Open `http://localhost:8000` in Chrome.

#### Verify

- [ ] The scene loads in the browser.
- [ ] You can orbit by dragging, zoom with the scroll wheel.
- [ ] Framerate is smooth (no obvious stutter).
- [ ] The reconstruction looks recognizable — the subject is identifiable
      even if some background is messy.

#### Commit progress

- [ ] On the pipeline repo, commit any helper scripts you wrote during
      this phase.
- [ ] Note the trained scene in `CLAUDE.md` under the "Scenes" section so
      future Claude Code sessions know it exists.

### What's NOT in this phase

- No Next.js app yet. Using the upstream viewer as-is.
- No agent. No chat. No tools.
- No Vercel deploy. Localhost only.
- No Hurricane Ian data. Easy scene only.
- No camera controls beyond what the upstream viewer provides.

### Troubleshooting

- **COLMAP registers very few images:** scene didn't have enough texture
  features (blank walls, uniform surfaces) or the scan moved too fast.
  Re-record with more deliberate motion and textured surroundings in frame.
- **Training PSNR plateaus low (<22) and looks blurry:** moving objects in
  the scene (people, leaves) confuse splat training. Pick a more static
  scene.
- **PLY loads in viewer but looks "exploded" or full of floaters:** the
  COLMAP poses were bad. Try `ns-process-data` with more frames (higher
  fps) or re-record. Floaters are usually a pose problem, not a training
  problem.
- **Viewer page is blank in Chrome:** check the dev console. Most common
  issues are CORS (use the http server, not opening the file directly) or
  a missing PLY path.

### Definition of done

When you can orbit your splat in Chrome, you're done with Phase 1.
Phase 2 will be wrapping this in a proper Next.js app with programmatic
camera control — the surface area the agent will eventually call.

Write the Phase 2 doc when you finish Phase 1, not before.

---

## 7. How to use Claude Code through all of this

A few patterns that pay off:

**At the start of every session,** open VS Code at the repo root and start
Claude Code. It'll pick up `CLAUDE.md` automatically. Confirm by asking
"what's this project?" — if it gives you back the architecture summary, the
skills system is wired up.

**When you SSH into Jetstream and start Claude Code there,** clone the
repo first so it can read `CLAUDE.md` and `.claude/skills/`. Now SSH Claude
Code knows the project too. This is the fix to the "Claude on the server
has no context" problem.

**When you write a new skill,** test it by asking Claude Code something
that should trigger it. If the skill doesn't load (you can tell from the
response — it'll be generic, not pipeline-aware), edit the description to
be more explicit. Trigger phrases are the lever; tweak them until firing
is reliable.

**When you find yourself re-explaining something to Claude Code,** that's
a signal to capture it in a skill or in `CLAUDE.md`. The repo evolves into
documentation of your workflow as you go.

**Commit early, commit often.** Every time something works, commit. The
git history of "Phase 0 complete ✓", "first COLMAP run succeeded ✓",
"first splat trained ✓", "viewer renders local PLY ✓" is one of the best
things about a project like this. Two months from now you'll look at the
log and see exactly when each piece clicked.

---

## 8. Today's literal next action

1. Create the repo, push the scaffold from section 4 (~30 min)
2. Install the skills from sections 3 and 4 (~15 min)
3. SSH into Jetstream, start the conda env setup, walk away while pip
   installs (~15 min of active work, then waiting)
4. While pip installs, record a 45-second phone video of something near
   you (~5 min)

By tonight, you should be in the middle of Phase 1 — either training a
splat or about to. By tomorrow, a splat rendering in your browser.

Once that works, the project is real.
