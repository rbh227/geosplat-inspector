# SplatAgent — Presentation Script (no slides — one diagram deck + live app)

*Spoken script, ~13–15 minutes at a natural pace. Text in **[brackets]** is a stage direction, not spoken.*

## Prep — two tabs, that's it

1. **The diagram deck** — open [`docs/demo/diagrams/index.html`](diagrams/index.html) in a browser. Seven tabs, in the order you'll speak them:

   | | Tab | Used in |
   |---|---|---|
   | 01 | Splats — what a Gaussian actually is | Part 1 |
   | 02 | COLMAP — where every photo was taken from | Part 1 |
   | 03 | Pipeline — drone video to a 2.9 MB building | Part 1 |
   | 04 | The app — the browser is the agent's eyes | Part 2 |
   | 05 | Two agents — the stage decides which tools exist | Part 3 |
   | 06 | Analyst — the app flies, the model looks | Part 3 |
   | 07 | Cleaner — statistics propose, the model judges, you approve | Part 3 |

   Everything is one self-contained file — no network, no build, nothing to log into. (Print-to-PDF gives you all seven as pages if you'd rather have a fallback.)
2. **The app**, with the trailer-park scene loaded — ideally the *raw, uncleaned* splat so the mess is visible. Have the cleaned building splat ready to load after.

Keep the deck tab and the app tab side by side; the script bounces between them.

---

## Part 1 — Splats, COLMAP, and the Pipeline (~5 min, all in the browser)

**[Deck tab 01 — Splats]**

I want to start with what a Gaussian Splat actually is, because it's not a mesh and it's not a photo. It's this: a 3D scene represented as a cloud of tiny, soft, coloured, semi-transparent blobs — Gaussians. **[Point at the panel]** And that panel is the entire model of one blob — a position, a size and tilt, an opacity, and a colour that shifts depending on the angle you look from. About fifty-nine numbers. That's it. One blob is nothing. A million of them, fitted together against real photographs, are a place — and because drawing them is just sorting and painting, you get photorealistic 3D that renders in real time, in a browser, on any laptop.

The key thing: the input is just ordinary imagery. No LiDAR, no depth sensors. Photos or video in, a navigable 3D scene out.

But before you can train the blobs, you need to know *where every photo was taken from*. That's the classic problem this next tool solves.

**[Deck tab 02 — COLMAP]**

This is COLMAP — structure from motion. Four steps, and the intuition is simple. First, in every photo, it finds thousands of distinctive little landmarks — a corner of a roof, a mailbox, a crack in the pavement. Then it matches those landmarks *across* photos: "this corner in frame 40 is the same corner in frame 41." And once you know the same physical point appears in multiple photos from different angles, you can triangulate — the same way your two eyes give you depth. COLMAP does this incrementally: it starts with two images, figures out their relative positions, then adds one image at a time, each time solving for both *where the camera was* and *where the 3D points are*, and continuously re-adjusting everything so it all stays consistent.

The output is two things: a camera pose for every frame, and a sparse 3D point cloud. That's the skeleton everything else hangs on — if these poses are wrong, nothing downstream can fix it.

**[Deck tab 03 — Pipeline]**

So here's the actual pipeline I ran, on real footage. The source is drone video from Hurricane Ian relief sites — Iona Point and Sanibel Island. And I want to be upfront about the material: this footage was *not* captured for reconstruction. It was damage-documentation flying — oblique angles, no GPS in the frames — so everything you'll see is scale-free, pure geometry recovered from pixels.

Walking the diagram left to right:

- **Thin the frames.** Video gives you thousands of near-duplicate, often blurry frames. I score sharpness and keep the best frame per window — 3,525 raw 4K frames became 705 good ones.
- **COLMAP** — what I just showed you. On this footage it registered all 705 frames and recovered about 600 thousand sparse points.
- **Pick a target.** Rather than reconstruct the whole site at once, the pipeline detects individual structures geometrically — points sticking up above the fitted ground plane, grouped into blobs, printed as a numbered top-down map. Pick a number, get that building's frame crops and a 3D bounding box. It found 8 structures on Iona and 10 on Sanibel.
- **Train.** Gaussian splat optimization with gsplat, plus three modifications I had to build to make *small-target* training work: steer the gaussian budget into the target box, mask the loss so background pixels can't demand coverage, and seed only inside the box. Without these, an oblique drone frame that sees the whole site makes the optimizer smear its budget over everything visible, and quality collapses.
- **Prune and package.** Kill the artifacts, verify quality by rendering at held-out real camera poses — photos the model never trained on.

**[Switch to the app — the raw trailer-park scene]**

And here's what that actually produces. This is a real reconstruction — a trailer park at the Iona Point relief site. You can fly through it, it renders in real time, and the structures are recognizably *there*.

Now let me point at the mess, because the mess is honest and it's also the setup for the rest of this talk. **[Fly to show each]** These floating blobs in the air — "floaters" — are gaussians the optimizer parked where a few frames disagreed. These streaks — needle-shaped gaussians stretched along the camera's viewing rays — are a classic artifact; they look like geometry from one angle and garbage from every other. And around the edges you get smeared background — sky and surroundings the optimizer painted with leftover budget. None of this is a bug in one tool; it's what happens when you reconstruct from opportunistic footage with no GPS and no planned coverage.

The per-building recipe shows the ceiling, though. **[Load the cleaned building splat]** A whole-area scene runs about a million gaussians. This single trailer, with the box-aware recipe, is **12,375 gaussians in a 2.9 megabyte file** at the same measured quality bar — one hundredth the size, and small enough that an AI agent can reason about every splat in it. Hold that thought.

**And here's the first place I want to flag real potential.** The pipeline was *not* the main focus of this project — I built it to get demo scenes, and it already works on footage that was never meant for reconstruction. That means the headroom is enormous, and I think it could be a main focus going forward: imagery actually captured for reconstruction — planned paths, overlap, GPS; joint pose-and-splat optimization to fix the residual blur, which I've diagnosed as likely a camera-pose problem; and feed-forward models like VGGT that produce poses and dense geometry in a single ~3-second forward pass instead of hours of SfM — I've already run it experimentally on one building. With better inputs and those upgrades, these stop being rough reconstructions and become real, faithful, measurable ones.

---

## Part 2 — The Interface (~3–4 min, live app)

**[Stay in the app]**

So once you have a splat, what do you do with it? Existing viewers let you look. I wanted a tool that lets you *work* — and that a human and an AI agent can share. So I built an editor.

**[Deck tab 04 — The app]** Everything runs locally: a Python backend that owns the splat data, the edit history and the agent loop, and a browser frontend that renders. No CUDA anywhere in the app — you only need a GPU to *create* splats, never to inspect them. Hold onto one detail on this diagram — the blue arrow. The browser doesn't just draw the scene for *you*; the frames it captures are literally what the model sees. I'll come back to that.

**[Back to the app]**

**[If not already loaded: drag-drop a scene]** You drag and drop a file — `.ply` and the common compressed formats — and you're in a classic editor layout: tool rail on the left, viewport in the middle, agent chat on the right, and a stage switch at the top I'll come back to.

The features, quickly:

**Navigation.** **[Orbit, then switch to fly]** Orbit for a first look, and a fly mode — WASD, drag to look — for getting inside a scene. Notice the movement pad down here: it lights up for *any* input source. Remember that — it's how you'll watch the agent fly in a minute.

**Selection.** **[Brush, lasso, then a box volume]** A full selection grammar modeled on the best existing splat editors. A resizable paint brush, a freeform lasso, a click-out polygon. And 3D volumes — sphere and box — where everything *outside* dims live, so you see exactly what a commit would keep before touching anything. Delete, keep-only, invert; Alt subtracts; Escape cancels.

**One shared history.** Every destructive edit — mine or the agent's — goes through the same backend endpoint into one authoritative edit history, with stable splat IDs. Undo works across both. If a backend edit fails, the viewer reloads the authoritative scene instead of silently drifting. One source of truth.

That's the design principle for the whole interface: **everything the agent can do, a human can do by hand — same tools, same selections, same history.** The agent isn't a black box that hands you back a mutated file. It's another user of the same editor, working in front of you.

---

## Part 3 — The Agents (~5 min, live app)

**[Point at the Clean / Understand switch]**

Which brings me to the part I find most exciting — and the second big place I see potential. There are two agents in this tool, and this switch gates them.

The key architectural idea first: **the browser is the agent's eyes.** The vision model never touches raw splat data — it sees captured frames from the same renderer you're looking at, and it acts through the same tools you just watched me use. And it's model-agnostic: it runs on Gemini, on any OpenAI-compatible API, or on a fully local open-weights vision model on our own GPU server — which is how I did most of my testing, for free.

**[Deck tab 05 — Two agents]** And the switch isn't a mode flag, it's containment. The outer ring is every tool the app has. The middle ring is what the Clean agent may call — the whole editor. The inner ring is the Analyst's entire world: navigate, capture, answer. Edit tools aren't hidden from it; they're *not in its specification*, and if one somehow got requested it's refused again at dispatch. Structurally read-only.

**The Analyst.** **[Back to the app. Switch to Understand. Ask: "How many trailers are in this scene?"]**

In Understand mode, you ask questions about the scene. Watch what happens: the *app* flies a framed survey orbit — the model doesn't drive the camera, so it can't get lost or stare at the sky. It captures views, then answers grounded only in what the survey actually shows. The captures persist for the conversation, so follow-ups reuse the same evidence.

**[While it runs — Deck tab 06 — Analyst]** That's the whole exchange: you ask, the app flies the orbit and captures, and the model gets exactly one job — look at these frames and answer. Notice who holds the camera in that diagram. It's never the model.

**The Cleaner.** **[Back to the app. Switch to Clean. Trigger cleanup.]**

You saw the mess — floaters, needles, background smear. Cleaning that by hand is tedious. So the Clean agent runs what I call a **judgment tour**, and the division of labor is the whole idea:

Statistics find the *candidates* — density analysis proposes where the subject is and clusters the likely junk. The model provides the *judgment* — the app flies the camera to each candidate cluster, tints it so you can see exactly what's being discussed, and asks the model one forced-choice question: junk, structure, or look closer.

**[While the tour runs — Deck tab 07 — Cleaner]** Three rows in this diagram, and the split is the whole design: what the app computes, the one question the model is asked, and where *you* sign. Follow the blue arrow — it's the only path in the system that deletes anything, and it starts at your approval.

**[Back to the app; let a couple of tour stops play out]**

And then — nothing gets deleted. Every verdict lands on a single review card listing every cluster. Nothing destructive fires until *I* approve, and the approval binds exactly what was reviewed. If the model got one wrong, I flip it in plain language — "keep B, that's a shed" — or reject the whole thing.

Notice what the model is *never* asked to do: it never invents 3D coordinates, it never picks which tool to call, it never free-runs. A failed model call just means a cluster gets kept — the safe default. That's why this survives even small local models: the app owns the control flow; the model is consulted only where visual judgment is genuinely needed.

**So, capabilities today, honestly:** it can survey a scene and answer grounded questions; it can separate the subject of a reconstruction from the noise; it can propose and — with approval — execute a full cleanup; and everything it does is visible, reviewable, and undoable.

**The challenges are real, and they're research questions:**

- **Perception is the bottleneck.** The machinery is solid and fully tested, but vision-language models are mediocre at counting and at fine-grained judgment on reconstruction artifacts. A splat render is not a photo — it's a domain these models never saw in training. What to show the model, and how to ask, is open work.
- **Grounding.** Getting a model to point at a region of an image reliably — and mapping that back into 3D — is fragile, and every model family does it differently.
- **Scale.** This works on a 12-thousand-gaussian trailer. A million-gaussian site needs the same ideas with smarter data structures.

**Flip each challenge over and it's an opportunity — and this is where it connects to our research**, even though this was a personal project:

- **Automated reconstruction QA.** The same agent that judges junk clusters can judge reconstruction *quality* — flagging holes, floaters, and blur automatically. A pipeline that grades its own output.
- **Semantic damage assessment.** These are post-disaster scenes. An analyst that flies a reconstruction and answers "which structures show roof damage?" — grounded in views, evidence attached — is a genuinely useful survey tool, and the scaffolding is what you just watched.
- **Human-in-the-loop at scale.** Eighteen structures detected across just two sites, more sites unprocessed. Nobody hand-cleans that. Propose-and-review is how one person supervises a whole dataset.
- **A testbed for VLM spatial reasoning.** The loop is local, model-agnostic, and instrumented — swap the model, run the same tour, measure the verdicts. That's an evaluation harness.

**[Closing — back to the scene orbiting]**

To close: I see two places with outsized potential here. The **agents** — the interaction pattern of propose-and-review over 3D scenes barely exists anywhere yet, and every capability jump in vision models makes this loop stronger with zero code changes. And the **pipeline** — which I built as a means to an end, and which I think deserves to become an end in itself: better imagery in, joint pose optimization, feed-forward geometry, and suddenly we're producing real, measurable reconstructions of these sites at scale. The two compound: better splats make the agent's judgment reliable, and a reliable agent makes large-scale reconstruction maintainable.

That's the direction I'd love for us to take this together. Happy to take questions — and happy to let the agent take some too.

---

## Appendix — numbers to have ready for Q&A

| Question you might get | Answer |
|---|---|
| Frame counts | 3,525 raw 4K frames → 705 after sharpness thinning; COLMAP registered 705/705 |
| Sparse points | ~604K (Iona) |
| Building splat size | Iona bldg01 (trailer): 12,375 gaussians, 2.9 MB, PSNR 21.7 on held-out real views |
| Whole-area comparison | ~0.8–1.2M gaussians per site scene at the same quality bar — ~100× larger |
| Training time | ~45 min per building on one L40S |
| Structures detected / trained | 8 on Iona + 10 on Sanibel = 18 detected; 3 trained so far |
| Why no scale/measurements | Source footage has no GPS — reconstructions are scale-free |
| VGGT | Feed-forward poses + dense points in one ~3.5 s pass; ran experimentally on one building; the pose A/B vs COLMAP crashed before a verdict — still open |
| Where does the blur come from | Diagnosed as likely imperfect camera poses; fix is joint pose + splat optimization (3R-GS / JOGS style) — top future-work item |
| Models the agent runs on | Gemini (default), any OpenAI-compatible API, or local vLLM (Qwen-VL) — must be a vision model |
| What if the model fails mid-cleanup | Safe default: cluster is kept; circuit breaker after repeated failures; Stop cancels cleanly |
