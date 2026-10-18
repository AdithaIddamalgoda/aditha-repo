# Board Detection and 3D Twin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Start a session with no corner taps, and add a geometry-based second observation channel (the 3D twin) to the decoder so moves decode reliably from the side-on tripod view.

**Architecture:** The recognizer exports per-square attention centroids; a RANSAC homography fit turns them into the board grid. From the grid, vanishing points give the focal length and a full camera pose. Pieces are projected as cylinder silhouettes to compute per-square visibility and predicted change masks, which join the recognizer's probabilities in the existing scorer. A beam of three hypotheses replaces the single best guess. A corpus-to-dataset adapter feeds the ChessQueries LoRA script for the server model.

**Tech Stack:** Existing web app (vanilla TypeScript, Vite, vitest, onnxruntime-web), existing `eval/` Python 3.12 tooling, ChessQueries repo (`viz/attention.py`, `scripts/lora_fewshot.py`). No new runtime dependency unless `docs/superpowers/research/2026-10-18-3d-twin-tooling.md` recommends one.

**Spec:** `docs/superpowers/specs/2026-10-17-chess-event-design.md`, section "Addendum, 2026-10-18". Research: `docs/superpowers/research/2026-10-18-chess-recognition-angles.md` and `docs/superpowers/research/2026-10-18-3d-twin-tooling.md`.

**Existing interfaces this plan builds on** (from `docs/superpowers/plans/2026-10-17-chess-camera.md`; if the live code names differ, use the live names and note them in the task's commit message): `Reading`, `LogProbs`, `Board`, `Rotation`, `toLogProbs`, `rotateLogProbs`, `START_BOARD`, `sq` in `web/src/types.ts` and `web/src/board.ts`; `GameState`, `Candidate`, `Tier`, `generate` in `web/src/candidates.ts`; `Scored`, `scoreAll`, `PRIORS` in `web/src/score.ts`; `Decoder`, `Outcome`, `DEFAULT_CONFIG` in `web/src/decoder.ts`; `Gray`, `Pt`, `Corners`, `homography`, `squareQuad`, `globalShift` in `web/src/homography.ts`; `Capture`, `StableFrame`, `CaptureEvent` in `web/src/capture.ts`; `Recognizer` in `web/src/recognizer.ts`; `eval/export_onnx.py`, `eval/dump_probs.py`, `eval/metrics.py`, `web/scripts/bench.ts`.

## Global Constraints

- Square index `a1 = 0 ... h8 = 63`; class order `empty, wP, wN, wB, wR, wQ, wK, bP, bN, bB, bR, bQ, bK`; probability floor `1e-3`.
- Analysis crop for masks and change detection: 128 x 128 grey, board centred, margin 10% of board width.
- Grid fit: RANSAC inlier threshold 0.3 square widths; minimum 48 of 64 inliers; otherwise the fit is rejected.
- Camera elevation hint shown below 50 degrees; target range 55 to 65.
- Default piece dimensions in square units, height then radius: pawn 0.8 / 0.20, knight 1.0 / 0.22, bishop 1.1 / 0.22, rook 0.95 / 0.24, queen 1.3 / 0.26, king 1.5 / 0.26.
- Twin weights: `lambda = 4.0` for the silhouette term; beam width 3; these live in `DEFAULT_CONFIG` and are tuned only through the benchmark.
- Every measurement goes into `eval/RESULTS.md` with date, model, device, and command.
- No images are stored by the app; the corpus on disk is the only image data.
- No Tencent, DNS, or Google change is made by any task; Task 7 stops and asks before renting a GPU.

## Review Focus

1. The model's attention centroids come out rotated 180 degrees relative to the real board. Expected: the grid still fits and the start check goes green after rotation. Test in Task 2.
2. The centroids land on a different repeating pattern such as a tablecloth, or the ultrawide lens bends the board. Expected: the fit is rejected or reported with high residual and the nudge handles appear. Test in Task 1.
3. Default piece heights are 20% off for the club's set. Expected: the combined scorer still beats recognizer-only. Sensitivity run in Task 6.
4. The tripod wobbles a few pixels between the two stable frames of a move. Expected: the observed change mask is computed after re-aligning the frames, and the move still scores. Test in Task 5.
5. Two identical pieces could have made the move and the recognizer cannot tell which. Expected: the beam keeps both and the next frame resolves it without a prompt. Test in Task 5.

## Decision gates

| Gate | Where | Pass condition | If it fails |
|------|-------|----------------|-------------|
| G4 Auto-grid | Task 1 and Task 2 | On the corpus start frames with hand-labelled corners, fitted corners within 0.15 square widths on at least 9 of 10 frames; on the phone, Start goes green with no taps on 3 of 3 tries | Nudge UI remains the path; learned corner model becomes a follow-up task |
| G5 Twin | Task 6 | Combined scorer has fewer silent errors and fewer prompts than recognizer-only on the corpus | Keep visibility weighting only; drop the silhouette term |
| G6 Fine-tune | Task 7 | Type accuracy on held-out corpus plies improves by 5 points or more | Serve the base large model as second opinion |

## Task dependency map

- Task 0 → Task 1 → Task 2 (auto-grid track).
- Task 3 → Task 4 → Task 5 → Task 6 (twin track; Task 3 needs only `homography.ts`).
- Task 7 is independent and can run in parallel on the VM.
- Read `docs/superpowers/research/2026-10-18-3d-twin-tooling.md` before Task 3. If it recommends a library for projection or masks, use it and keep the signatures below.

---

### Task 0: Attention centroids in the recognizer output

**Files:**
- Modify: `eval/export_onnx.py`, `eval/dump_probs.py`, `eval/contract.py`
- Modify: `web/src/types.ts` (`Reading`), `web/src/worker/onnx.worker.ts`, `web/src/recognizer.ts`
- Test: `eval/tests/test_centroids.py`, `web/test/recognizer.test.ts`

**Interfaces:**
- Produces: ONNX output `centroids` of shape `[64, 2]`, normalised to `[0, 1]` in the model input's x and y, in the model's own square order (same order as `probs`). `Reading.centroids?: number[][]` carries it through the contract; `dump_probs.py` writes it when present.
- `centroids_from_attention(attn: Tensor[64, H, W]) -> Tensor[64, 2]` in `eval/export_onnx.py`, built from the logic in the repo's `viz/attention.py`.

- [ ] **Step 1: Write the failing test** `test_centroids_match_pytorch`: on one corpus photo, ONNX `centroids` vs PyTorch centroids from `viz/attention.py` differ by at most 0.01 of the image width per point.
- [ ] **Step 2: Run** `uv run pytest eval/tests/test_centroids.py -q` → FAIL.
- [ ] **Step 3: Implement** the second output in the exported graph (softmax over the attention map, then expected x and y). Keep `probs` and `embeddings` unchanged.
- [ ] **Step 4: Run** → PASS. Re-run `eval/parity.py` to confirm `probs` are unchanged.
- [ ] **Step 5: Web side.** Extend `Reading` and the worker to pass `centroids` through; `web/test/recognizer.test.ts` gains `FileRecognizer passes centroids through unchanged`.
- [ ] **Step 6: Commit** `feat: export attention centroids with the recognizer`

---

### Task 1: Grid fit from centroids

**Files:**
- Create: `web/src/gridfit.ts`
- Test: `web/test/gridfit.test.ts`
- Create: `eval/corpus/<game>/corners.json` for 10 start frames, hand-labelled `{ "a1": [x,y], "h1": [x,y], "h8": [x,y], "a8": [x,y] }` in photo pixels (the owner or the builder labels these once; they are the G4 ground truth)
- Create: `web/scripts/gridbench.ts`

**Interfaces:**
```ts
export interface GridFit { H: Float64Array; corners: Corners; inliers: number; rms: number }  // corners in the model's square order: index 0 is the model's "a1"
export function fitGrid(centroids: Pt[], opts?: { threshold?: number; minInliers?: number; iterations?: number }): GridFit | null;
export function idealCentre(square: number): Pt;   // ((file + 0.5) / 8, (rank + 0.5) / 8)
```
Algorithm: RANSAC over random 4-square samples, `homography` from the four ideal centres to the four centroids, count centroids within `threshold` square widths of their projected ideal centre, keep the best, then refit a least-squares DLT on all inliers and report `rms` in square widths. Defaults: threshold 0.3, minInliers 48, iterations 500.

- [ ] **Step 1: Write failing tests** `recovers corners from a synthetic homography with 0.1-square noise`, `tolerates 12 outliers` (corners within 0.05 square), `returns null with 20 outliers at the same wrong lattice` (Review Focus 2), `rms is reported in square widths`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: `gridbench.ts`** runs `fitGrid` on the corpus start-frame readings and compares with `corners.json` after resolving the best of four rotations; prints per-frame error in square widths and appends to `eval/RESULTS.md`. Decide G4 part one.
- [ ] **Step 6: Commit** `feat(web): fit the board grid from attention centroids`

---

### Task 2: Start with no taps

**Files:**
- Modify: `web/src/ui/setup.ts`, `web/src/capture.ts`, `web/src/app.ts`
- Create: `web/src/ui/nudge.ts`, `web/src/lens.ts`
- Test: `web/test/lens.test.ts`, `web/test/setupflow.test.ts`

**Interfaces:**
```ts
// lens.ts
export function pickRearCamera(devices: MediaDeviceInfo[]): string | null;   // prefers labels matching /back|rear|environment/i and rejects /ultra|wide|tele|front/i; null when none
// capture.ts additions
refit(): Promise<void>;   // re-runs the recognizer on the current frame, fitGrid, setCorners; called on 'bumped'
// setup flow (app.ts)
startSession(): Promise<'green' | 'nudge'>;  // read frame -> fitGrid -> setCorners -> decoder.calibrate -> green when ok, else nudge
```
Nudge UI: four handles with 44 px hit areas, a loupe at 3x under the dragged handle, undo stack of corner positions, "Find again" calling `refit`, "Use this grid" calling `calibrate` again. Elevation hint from Task 3's `elevationDeg` once available; until then the hint is omitted.

- [ ] **Step 1: Write failing tests** `pickRearCamera prefers the main back camera over ultra wide` (labels from an iPhone and a Pixel), `startSession returns green for a start reading whose centroids are rotated 180 degrees` (FileRecognizer with rotated centroids and probs; Review Focus 1).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Phone check.** Three cold starts on the tripod: record whether each went green with no taps, the fitted `rms`, and the time from Start to green. Decide G4 part two in `eval/RESULTS.md`.
- [ ] **Step 6: Commit** `feat(web): start with no taps, nudge handles, main-lens selection`

---

### Task 3: Camera pose from the grid

**Files:**
- Create: `web/src/camera.ts`
- Test: `web/test/camera.test.ts`

**Interfaces:**
```ts
export interface Intrinsics { f: number; cx: number; cy: number }
export interface Pose { R: Float64Array; t: Float64Array }          // 3x3 row-major, 3
export function focalFromVanishing(H: Float64Array, w: number, h: number): number | null;  // vanishing points H·(1,0,0) and H·(0,1,0); f² = −(v1−c)·(v2−c); null when negative
export function poseFromHomography(H: Float64Array, K: Intrinsics): Pose;   // K⁻¹H = λ[r1 r2 t], r3 = r1 × r2, orthonormalise R with SVD
export function elevationDeg(pose: Pose): number;   // angle between the board plane and the line from the board centre to the camera centre C = −Rᵀt
export function project(K: Intrinsics, pose: Pose, X: [number, number, number]): Pt;  // board units: x, y in [0,8], z up in square widths
```

- [ ] **Step 1: Write failing tests** with synthetic cameras at 45 and 60 degrees elevation: `focalFromVanishing recovers f within 5%`, `elevationDeg within 2 degrees`, `project maps board corners back onto H`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (3x3 SVD hand-rolled or from the library the research file recommends).
- [ ] **Step 4: Run** → PASS. **Step 5: Wire the elevation hint** into the setup screen. **Step 6: Commit** `feat(web): camera pose and elevation from the grid`

---

### Task 4: The twin: silhouettes, visibility, change masks

**Files:**
- Create: `web/src/twin.ts`
- Test: `web/test/twin.test.ts`

**Interfaces:**
```ts
export interface Mask { w: number; h: number; data: Uint8Array }     // 128 x 128 analysis crop
export interface PieceDims { h: number; r: number }
export const DEFAULT_DIMS: Record<Exclude<PieceClass, 'empty'>, PieceDims>;   // Global Constraints values; colour variants share dims
export class Twin {
  constructor(K: Intrinsics, pose: Pose, cropToImage: Float64Array /* 3x3 mapping crop px -> image px */, dims?: Partial<typeof DEFAULT_DIMS>);
  pieceMask(square: number, cls: PieceClass): Mask;          // cylinder: project top and bottom circles, hull
  render(board: Board): Mask;                                 // painter's order, far to near
  visibility(board: Board): Float32Array;                     // 64, fraction of each piece's mask not covered by nearer pieces; 1 for empty squares
  changeMask(a: Board, b: Board): Mask;                       // render(a) XOR render(b)
}
```

- [ ] **Step 1: Write failing tests** on a synthetic 60-degree camera: `king mask is taller than pawn mask`, `a pawn directly in front of a king from the camera's side reduces the king's visibility below 0.7`, `visibility of a piece with nothing in front is 1`, `changeMask of e2e4 is non-zero only around e2 and e4`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** Rasterise polygons with a scanline fill; no WebGL.
- [ ] **Step 4: Run** → PASS. **Step 5: Commit** `feat(web): 3D twin silhouettes and visibility`

---

### Task 5: Twin terms in the scorer and a beam in the decoder

**Files:**
- Modify: `web/src/score.ts`, `web/src/decoder.ts`, `web/src/homography.ts`
- Test: `web/test/score.test.ts`, `web/test/decoder.test.ts`

**Interfaces:**
```ts
// homography.ts addition
export function observedChange(prev: Gray, cur: Gray, thresh: number): Mask;   // align cur to prev with globalShift first, brightness-normalise, |Δ| > thresh; 128 x 128
// score.ts
export interface TwinTerms { visibility?: Float32Array; silhouette?: { observed: Mask; twin: Twin; lambda: number } }
export function silhouetteScore(cand: Board, prev: Board, observed: Mask, twin: Twin): number;   // IoU inside the union of predicted and observed
export function scoreAll(s: GameState, cands: Candidate[], lp: LogProbs, current: Rotation, rotPrior: number, terms?: TwinTerms): Scored[];
// recognizer term per square becomes v_s * (lp[cand] - lp[current]); silhouette adds lambda * IoU
// decoder.ts
export interface DecoderConfig { /* existing */ lambda: number; beamWidth: number }   // 4.0, 3
export interface Hypothesis { state: GameState; logScore: number }
// Decoder keeps `beam: Hypothesis[]`; step() expands each hypothesis, prunes to beamWidth, returns 'move' only when the best hypothesis leads the second by marginMin; prerender(): Mask[] renders change masks for all legal replies of the best hypothesis
```

- [ ] **Step 1: Write failing tests** `silhouetteScore ranks the true knight move above the other knight's move when lp is uniform on both` (Review Focus 5 primitive), `visibility weighting removes the penalty from a hidden square`, `observedChange matches after a 3 px shift` (Review Focus 4), `ambiguous frame keeps two hypotheses and the next frame resolves without ask` (Review Focus 5).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** Existing decoder tests must still pass with `terms` omitted.
- [ ] **Step 4: Run** → PASS. **Step 5: Commit** `feat(web): twin terms in the scorer and a hypothesis beam`

---

### Task 6: Benchmark the twin (gate G5)

**Files:**
- Modify: `web/scripts/bench.ts`
- Modify: `eval/RESULTS.md`

**Interfaces:**
- `npm run bench -- --corpus ../eval/corpus --model lite --mode recognizer|silhouette|combined [--no-visibility] [--lambda 4] [--dims-scale 0.8|1.2]`. For each game: fit the grid from ply 000's centroids, build `Twin` from it, compute `observedChange` between consecutive ply JPEGs, and run the decoder in the chosen mode. Same output columns as before plus the mode.

- [ ] **Step 1: Implement the modes.**
- [ ] **Step 2: Run** recognizer, silhouette, combined, combined without visibility, and combined with `--dims-scale 0.8` and `1.2` (Review Focus 3). Tables into `RESULTS.md`.
- [ ] **Step 3: Sweep** `lambda` over 1, 2, 4, 8 on combined. Set `DEFAULT_CONFIG.lambda` to the best. Decide G5.
- [ ] **Step 4: Commit** `feat(web): benchmark modes for the twin`

---

### Task 7: Corpus to dataset, first fine-tune, serve as second opinion

**Files:**
- Create: `eval/to_cq_dataset.py`, `eval/finetune.md`
- Modify: `server/app.py` (if the server exists), `eval/RESULTS.md`

**Interfaces:**
- `to_cq_dataset.py --corpus eval/corpus --out eval/datasets/club_v1 --split-by-game 0.7 0.15 0.15` writes the dataset in the exact format `scripts/lora_fewshot.py` registers (read that script and its dataset registry first; mirror an existing dataset's loader, and document the format in `eval/finetune.md`). Each ply JPEG is labelled by the FEN derived from the PGN; takeback plies use the comment convention from the corpus README.
- Server: `POST /read?model=tuned` loads the LoRA-merged weights when present; `/config` advertises `tuned: true`.

- [ ] **Step 1: Write the adapter** with a test `test_split_by_game_has_no_game_in_two_splits`.
- [ ] **Step 2: Fine-tune ChessQ Lite** with the repo's script, rank 8, 1500 steps, on the dev VM overnight. If it exceeds 12 hours or memory, **stop and ask** before renting a GPU.
- [ ] **Step 3: Evaluate** with `eval/metrics.py` on the held-out split: occupancy, colour, type, calibration, before and after. Decide G6.
- [ ] **Step 4: If G6 passes,** repeat for the large model and serve it as `model=tuned`. Export the tuned Lite through Task 0's ONNX path and run parity; it becomes the on-device default only after the Task 6 benchmark is re-run with it.
- [ ] **Step 5: Commit** `feat(eval): corpus-to-dataset adapter and first fine-tune results`
