# Chess Camera Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A phone on a tripod watches a casual over-the-board chess game; a static web app mirrors it as a live virtual board, exports PGN, and offers a hidden-by-default eval bar.

**Architecture:** A recognizer (ChessQ Lite, on-device via ONNX if the Phase 0 spike passes, else a small server) turns one stable photo into 64x13 per-square probabilities. A position-aware decoder in TypeScript scores candidate explanations (no change, legal move, undo, two-ply, illegal move) under four board rotations and runs a state machine that waits on transient frames and asks the user only when the margin is small. The recognizer-to-decoder contract is a JSON file, so the same decoder code runs the unit tests, the corpus benchmark, and the app.

**Tech Stack:** Vanilla TypeScript + Vite (no framework), chess.js (BSD), chessground (GPL-3.0), stockfish npm (WASM, single-thread), onnxruntime-web, vitest. Eval tooling: Python 3.12 via uv, PyTorch, ChessQueries repo, onnxruntime.

**Spec:** This document's "Design decisions" section is the spec; it condenses the v2 plan agreed on 2026-10-17 and the two review rounds. No separate spec file exists.

**Project root:** `/home/ubuntu/coding-projects/chess_daily` (new git repo). Paths below are relative to it.

## Design decisions (spec)

- **LLMs and engines stay out of the decoder.** Recognition is a frozen open-source model; decision is deterministic code; Stockfish only drives the eval bar.
- **Contract = JSON.** One `Reading` per photo: `{version, model, classes[], probs[64][C], embeddings?, ms}`. Squares in a1..h1, a2..h2, ..., h8 order. Classes listed by name; consumers map by name, never by index.
- **Decoder scoring.** For a candidate board `C` against the tracked board `P`: `score = Σ_{s ∈ diff(P,C)} (lp[s][C[s]] − lp[s][P[s]])` where `lp` is log of probabilities floored at `1e-3`. "No change" scores 0. Tier log-priors are added. The maximum wins if `score ≥ acceptMin` and the margin to the runner-up is `≥ marginMin`; otherwise the frame is pending, then after `pendingMax` frames the user is asked with ranked candidates.
- **Rotation.** The model may emit the board rotated. Every frame is scored under all four rotations of the reading with a prior toward the current rotation; session start calibrates the rotation against the initial position.
- **Candidate tiers and priors (tunable, one object):** none 0, legal 0, undo1 −2, undo2 −3, twoply −3, illegal −6.
- **Transient states** (hand mid-air, piece lifted while thinking, captured piece resting on the edge) are pending, not prompts.
- **Illegal moves** are tracked on a plain 64-square array. The PGN movetext stops at the first illegal move with a comment; the export is marked verifiable only up to that ply.
- **Promotion** defaults to queen when the type is uncertain. "Fix last move" covers under-promotion.
- **Games start from the initial position.** Orientation and White's side come from four corner taps starting at a1. Mid-game join is out of scope.
- **Capture.** Stability from frame diff on a 64x64 grey crop; a frame is read only when brightness-normalised per-square energy against the last accepted frame exceeds a threshold; up to three stable frames per move are averaged before decoding. The homography from the corner taps is used for per-square energy and bump detection, never to warp the model input. The model gets a roughly square crop with a margin.
- **Where inference runs** is decided by a time-boxed spike (Task 4). On-device is the default if it passes; the server is optional and only for a second opinion.
- **Gate metrics** on the user's own recorded games: silently wrong plies per game = 0; prompts ≤ 5% of plies; seconds per read on the target device recorded.
- **Images are never stored** unless the user opts in to saving frames the decoder flagged uncertain.
- **Licensing.** App source under GPL-3.0 (chessground). Weights are PolyForm Noncommercial 1.0.0: non-commercial use only, notice ships with the app. ChessReD is CC BY-NC-SA and is used only for eval.
- **Tencent.** Nothing hosted depends on the EdgeOne personal plan (expires 2026-10-20) or on the cricket-daily resources. Any firewall, DNS, or new-resource change needs explicit approval from the user in the session that makes it.

## Global Constraints

- Node 22, TypeScript `strict: true`, Vite 5+, vitest. No UI framework.
- Python 3.12 via `uv` for `eval/`; the system Python 3.14 is not used.
- Square index: `a1 = 0`, `b1 = 1`, ..., `h1 = 7`, `a2 = 8`, ..., `h8 = 63`.
- Class names: `empty, wP, wN, wB, wR, wQ, wK, bP, bN, bB, bR, bQ, bK` (this order is the app's canonical order; readings may list classes in any order).
- Probability floor `1e-3` before any log.
- Default thresholds: `stableMs = 400`, `pendingMax = 3`, `acceptMin = 2.0`, `marginMin = 1.5`, `disagreeP = 0.2`.
- Every Phase 0 number goes into `eval/RESULTS.md` with the date, model, device, and command used.
- No photo, frame, or crop is written to disk by the app unless the opt-in save toggle is on.
- No Tencent resource is created or changed by a task; tasks that need one stop and ask.

## Review Focus

1. The model flips the board 180° between two consecutive frames mid-game. Expected: the move is still decoded. Test in Task 8.
2. A stable frame is missed and the next frame is two plies ahead. Expected: both plies are recovered via the two-ply tier. Test in Task 8.
3. A player lifts a piece and holds it while thinking; the frame shows an empty square and nothing else. Expected: pending, no prompt, then the real move is decoded from the next frame. Test in Task 8.
4. A player makes an illegal move and both players continue. Expected: the move is tracked on the raw board, later legal moves still decode, and the PGN stops with a comment at that ply. Tests in Task 8 and Task 10.
5. The tripod is knocked and every later frame is unexplained. Expected: the app detects the shift and prompts to re-frame rather than waiting forever. Test in Task 12.

## Decision gates

| Gate | Where measured | Pass condition | If it fails |
|------|----------------|----------------|-------------|
| G0 Lite loads | Task 2 | Lite loads with repo code and its argmax matches chessq.org's Lite reading on the user's reference photo on ≥ 60 of 64 squares | Stop. Ask the author or fall back to the paper ViT-L as default. |
| G1 On-device | Task 4 | ONNX parity (max abs prob diff ≤ 0.02, argmax agreement ≥ 99%) and read time on the user's phone ≤ 3 s WebGPU or ≤ 8 s WASM | Server path: Task 17. |
| G2 Decoder | Task 9 | On the user's recorded games: silently wrong plies = 0, prompts ≤ 5% of plies | Tune priors and thresholds; if still failing, run the adaptation experiment (Task 18) or the second opinion (Task 17). |

## Task dependency map

- Track A, data and spikes: Task 1 → Task 2 → Task 3 → Task 4. User records games in parallel (Task 1 protocol).
- Track B, decoder (no network, synthetic data): Task 5 → Task 6 → Task 7 → Task 8 → Task 10. Independent of Track A until Task 9.
- Task 9 needs Tracks A and B.
- Track C, capture app: Task 11 → Task 12 → Task 13 → Task 14, needs Task 5 only.
- Tasks 15 and 16 after Task 14. Task 17 only if G1 fails. Task 18 only if G2 fails.

---

### Task 0: Repository and toolchain

**Files:**
- Create: `README.md`, `LICENSE` (GPL-3.0 text), `THIRD_PARTY.md`, `.gitignore`
- Create: `web/package.json`, `web/tsconfig.json`, `web/vite.config.ts`, `web/index.html`, `web/src/main.ts`
- Create: `eval/pyproject.toml`, `eval/README.md`, `eval/RESULTS.md`

**Interfaces:**
- Produces: `npm test` runs vitest in `web/`; `uv run` works in `eval/` with Python 3.12.

- [ ] **Step 1: `git init`, write `.gitignore`** covering `node_modules/`, `web/dist/`, `eval/.venv/`, `*.onnx`, `web/public/models/`. Corpus photos under `eval/corpus/` stay tracked: they are the test set, so the repo will be large.
- [ ] **Step 2: Write `THIRD_PARTY.md`** listing ChessQueries weights (PolyForm Noncommercial 1.0.0, link), chessground (GPL-3.0), chess.js (BSD-2), stockfish (GPL-3.0), ChessReD (CC BY-NC-SA, eval only). Copy the PolyForm notice text verbatim.
- [ ] **Step 3: Scaffold `web/`** with `npm create vite@latest` (vanilla-ts), add `vitest`, `chess.js`, `chessground`, `onnxruntime-web`, `stockfish`. Add `"test": "vitest run"` and `"bench": "tsx scripts/bench.ts"` scripts.
- [ ] **Step 4: Scaffold `eval/`** with `uv init --python 3.12`; add `torch`, `torchvision`, `onnx`, `onnxruntime`, `pillow`, `numpy`, `safetensors`, `huggingface_hub`. Record in `eval/README.md` how the ChessQueries repo is cloned into `eval/vendor/chessqueries` (git submodule) and how weights are fetched.
- [ ] **Step 5: Verify** `cd web && npm test` prints "no test files" without error, and `cd eval && uv run python -c "import torch; print(torch.__version__)"` prints a version.
- [ ] **Step 6: Commit** `chore: scaffold web and eval toolchains`

---

### Task 1: Corpus format and recording protocol

**Files:**
- Create: `eval/corpus/README.md`, `eval/make_corpus.py`
- Test: `eval/tests/test_make_corpus.py`

**Interfaces:**
- Produces corpus layout used by Tasks 2, 4, 9:
  ```
  eval/corpus/<game>/game.pgn
  eval/corpus/<game>/setup.json     {"corners_hint": "a1 bottom-left", "piece_set": "...", "camera": "...", "notes": "..."}
  eval/corpus/<game>/plies/000.jpg  # start position, then 001.jpg after ply 1, ...
  eval/corpus/<game>/readings/<model>/000.json  # one Reading per photo (Task 2 writes these)
  ```
- `make_corpus(photos_dir: Path, pgn_path: Path, out_dir: Path) -> int` returns the ply count and raises `ValueError` when photo count ≠ plies + 1.

- [ ] **Step 1: Write `eval/corpus/README.md`**, the recording protocol for the user: phone on the tripod in the usual event setup; one photo per ply after the hand leaves; include the start position; include at least one capture, one castling, one takeback (photograph the position before and after the retraction, and write the retraction in the PGN as a comment `{takeback}` so the ply count still matches), one frame with a hand resting in view, one lighting change, one knocked-over piece; one game on a second board or piece set if available; a tight and a loose crop of the same position. Two games minimum.
- [ ] **Step 2: Write the failing test** `test_make_corpus_rejects_wrong_count` (3 photos, 1-ply PGN → `ValueError`) and `test_make_corpus_layout` (3 photos, 2-ply PGN → `plies/000.jpg..002.jpg` exist and return value is 2).
- [ ] **Step 3: Run** `uv run pytest eval/tests -q` → FAIL.
- [ ] **Step 4: Implement `make_corpus`** in `eval/make_corpus.py` with a CLI `python -m make_corpus <photos_dir> <game.pgn> <out_dir>`; sort photos by name; count plies with `chess.pgn` (add `python-chess`).
- [ ] **Step 5: Run** `uv run pytest eval/tests -q` → PASS.
- [ ] **Step 6: Commit** `feat(eval): corpus layout and recording protocol`

---

### Task 2: Probability dumper (the Python side of the contract)

**Files:**
- Create: `eval/dump_probs.py`, `eval/contract.py`
- Test: `eval/tests/test_contract.py`

**Interfaces:**
- `write_reading(path: Path, model: str, classes: list[str], probs: np.ndarray, embeddings: np.ndarray | None, ms: float) -> None` validates shape `(64, len(classes))`, rows summing to 1 ± 1e-3.
- `load_model(name: Literal["lite","large"]) -> tuple[torch.nn.Module, list[str], Callable[[Image], torch.Tensor]]` returns the model, its class names in the model's own order, and its preprocessing.
- `predict_probs(model, pre, image: Image) -> tuple[np.ndarray, np.ndarray]` returns `(probs[64, C], embeddings[64, D])` by calling the model directly (the repo's `Predictor.predict` returns argmax only).
- CLI: `uv run python dump_probs.py --model lite --corpus eval/corpus/<game> [--time]` writes `readings/lite/NNN.json` and, with `--time`, prints mean seconds per photo and peak RSS.

- [ ] **Step 1: Write the failing test** `test_write_reading_shape` (wrong shape → `ValueError`) and `test_write_reading_roundtrip` (written JSON has keys `version, model, classes, probs, ms`, 64 rows).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement `eval/contract.py`**.
- [ ] **Step 4: Implement `load_model`** by reading the ChessQueries repo's model construction and `core/square.py`; confirm the square order the model emits and reorder to a1..h8 if it differs; record the finding in `eval/README.md`. Confirm Lite loads at all (its loader code may not mention ViT-S): if it does not, build the ViT-S config by hand from the Hugging Face card and the safetensors keys.
- [ ] **Step 5: Implement `predict_probs`** taking the pre-head 64 query embeddings as the second output.
- [ ] **Step 6: Gate G0.** Run the dumper on the user's reference photo and compare argmax to the chessq.org Lite reading the user recorded. Write the per-square agreement to `eval/RESULTS.md`. ≥ 60/64 passes.
- [ ] **Step 7: Commit** `feat(eval): dump 64x13 readings from ChessQ Lite and ViT-L`

---

### Task 3: VM timing and corpus readings

**Files:**
- Modify: `eval/RESULTS.md`

- [ ] **Step 1: Run** `uv run python dump_probs.py --model lite --corpus eval/corpus/<each game> --time` for every recorded game. Record s/photo and peak RSS.
- [ ] **Step 2: Run the same with `--model large`** on one game only. Record s/photo and peak RSS. Stop and record "OOM" if the process is killed; do not retry with swap.
- [ ] **Step 3: Compute per-square metrics** with a new `eval/metrics.py` (`uv run python metrics.py --corpus <game> --model lite`): using the PGN, derive the true board per ply; report occupancy accuracy, colour accuracy on occupied squares, type accuracy on occupied squares, and expected calibration error over 10 bins, each for the best rotation of the reading. Write to `RESULTS.md`.
- [ ] **Step 4: Commit** `docs(eval): VM timing and per-square metrics`

---

### Task 4: ONNX export spike (gate G1, time-box one day)

**Files:**
- Create: `eval/export_onnx.py`, `eval/parity.py`, `web/spike/index.html`, `web/spike/spike.ts`

**Interfaces:**
- `export_onnx.py --model lite --out web/public/models/chessq-lite.onnx` exports with fixed input `1x3xHxW` at the model's training resolution, opset 17, outputs named `probs` (`64xC`) and `embeddings` (`64xD`).
- `parity.py --corpus <game> --onnx <path>` prints max abs prob diff and argmax agreement across the corpus.
- `web/spike/` is a page that loads the ONNX with onnxruntime-web, reads one bundled photo, prints ms for `webgpu` and `wasm` providers and the top class per square.

- [ ] **Step 1: Export.** If `torch.onnx.export` fails on an op, try `dynamo=True`; if it still fails after the time-box, record the failing op in `RESULTS.md` and declare G1 failed.
- [ ] **Step 2: Parity** against the PyTorch readings on one corpus game. Record numbers.
- [ ] **Step 3: Quantize** with `onnxruntime.quantization.quantize_dynamic` to int8 and re-run parity; keep whichever of fp16/int8 passes parity at the smaller size.
- [ ] **Step 4: Phone timing.** Serve `web/spike` over the phone's reachable HTTPS (Vite `--host` on a laptop on the same Wi-Fi with `@vitejs/plugin-basic-ssl`, or a temporary EdgeOne Pages deploy of the spike only). Record phone model, OS version, provider, ms, and whether WebGPU was available.
- [ ] **Step 5: Decide G1** in `RESULTS.md`: on-device or server. Commit `feat(eval): ONNX export, parity, and phone spike`.

---

### Task 5: Reading types and board model

**Files:**
- Create: `web/src/types.ts`, `web/src/board.ts`
- Test: `web/test/board.test.ts`

**Interfaces (produces):**
```ts
export const CLASSES = ['empty','wP','wN','wB','wR','wQ','wK','bP','bN','bB','bR','bQ','bK'] as const;
export type PieceClass = typeof CLASSES[number];
export interface Reading { version: 1; model: string; classes: readonly string[]; probs: number[][]; embeddings?: number[][]; ms?: number }
export type LogProbs = Float32Array;            // 64 * 13, CLASSES order, floored and logged
export type Board = PieceClass[];               // length 64, index a1=0..h8=63
export type Rotation = 0 | 1 | 2 | 3;           // quarter turns clockwise
export function toLogProbs(r: Reading, floor?: number): LogProbs;   // maps classes by name; throws on unknown name
export function meanLogProbs(lps: LogProbs[]): LogProbs;            // mean in probability space, re-floored
export function rotateBoard(b: Board, k: Rotation): Board;
export function rotateLogProbs(lp: LogProbs, k: Rotation): LogProbs;
export function boardFromFen(fen: string): Board;
export function diffSquares(a: Board, b: Board): number[];
export const START_BOARD: Board;
export function sq(name: string): number;        // 'e4' -> 28
```

- [ ] **Step 1: Write failing tests** `toLogProbs maps classes by name` (a reading whose classes are shuffled yields the same LogProbs as the canonical order), `toLogProbs floors at 1e-3` (prob 0 → `Math.log(1e-3)`), `rotateBoard 4 times is identity`, `rotateBoard(START,2) puts wK on e8`, `boardFromFen(start) equals START_BOARD`, `diffSquares(START, after e2e4) is [sq('e2'), sq('e4')]`.
- [ ] **Step 2: Run** `npm test` → FAIL.
- [ ] **Step 3: Implement** `types.ts` and `board.ts`. Rotation of a 64-grid: `(file, rank) -> (rank, 7-file)` per quarter turn.
- [ ] **Step 4: Run** → PASS. **Step 5: Commit** `feat(web): reading contract and board model`

---

### Task 6: Candidate generation

**Files:**
- Create: `web/src/game.ts`, `web/src/candidates.ts`
- Test: `web/test/candidates.test.ts`

**Interfaces (produces):**
```ts
export interface GameState { moves: string[]; board: Board; fen: string | null; legal: boolean }  // moves are UCI; fen null once illegal
export function initialState(): GameState;
export function applyMoves(s: GameState, uci: string[]): GameState;   // via chess.js while legal; throws if illegal in legal state
export function applyIllegal(s: GameState, from: number, to: number): GameState;  // raw array move, legal=false
export function undo(s: GameState, n: 1 | 2): GameState;

export type Tier = 'none' | 'legal' | 'undo1' | 'undo2' | 'twoply' | 'illegal';
export interface Candidate { tier: Tier; moves: string[]; undo: 0 | 1 | 2; board: Board; illegal?: { from: number; to: number } }
export function generate(s: GameState, tiers: Tier[]): Candidate[];
```
Rules: `legal` = all chess.js legal moves from `s`; promotions generate all four pieces; `twoply` = every legal reply to every legal move (skip if `!s.legal`); `undo1`/`undo2` need that many moves on the stack; `illegal` = every occupied square to every other square of the board array, excluding moves already in `legal`. When `s.legal` is false, `generate` still returns `none`, `undo*`, `illegal`, and tries chess.js `load(fen, {skipValidation:true})` for `legal`; if that throws, `legal` and `twoply` are empty.

- [ ] **Step 1: Write failing tests** `legal tier from start has 20 candidates`, `twoply from start has 400 candidates`, `undo1 restores previous board`, `illegal tier excludes legal moves and includes e1 to e3 from start`, `promotion yields four candidates`, `after applyIllegal, generate still yields none and illegal`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(web): game state and candidate tiers`

---

### Task 7: Scoring

**Files:**
- Create: `web/src/score.ts`
- Test: `web/test/score.test.ts`

**Interfaces (produces):**
```ts
export interface Scored { candidate: Candidate; rotation: Rotation; score: number }  // score includes tier prior
export const PRIORS: Record<Tier, number>;  // none 0, legal 0, undo1 -2, undo2 -3, twoply -3, illegal -6
export function scoreCandidate(current: Board, cand: Board, lp: LogProbs): number;  // Σ over diffSquares of lp[cand] - lp[current]
export function disagreeing(board: Board, lp: LogProbs, pMin: number): number[];      // squares where p(board[s]) < pMin
export function scoreAll(s: GameState, cands: Candidate[], lp: LogProbs, current: Rotation, rotPrior: number): Scored[];  // all 4 rotations, sorted desc; non-current rotations get rotPrior added (default -1)
```

- [ ] **Step 1: Write failing tests** with a helper `synthReading(board: Board, pCorrect = 0.9, noise?: {square:number; cls:PieceClass; p:number}[])` placed in `web/test/synth.ts`: `no-change scores 0`, `the true move outscores every other legal move on a clean reading`, `scoreAll picks rotation 2 when the reading is rotated`, `disagreeing lists exactly the squares a noise entry corrupts`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(web): candidate scoring under rotation`

---

### Task 8: Decoder state machine

**Files:**
- Create: `web/src/decoder.ts`
- Test: `web/test/decoder.test.ts`

**Interfaces (produces):**
```ts
export interface DecoderConfig { floor: number; priors: Record<Tier, number>; rotPrior: number; acceptMin: number; marginMin: number; disagreeP: number; disagreeMax: number; pendingMax: number }
export const DEFAULT_CONFIG: DecoderConfig;  // values from Global Constraints; disagreeMax 2
export type Outcome =
  | { kind: 'nochange' }
  | { kind: 'move'; scored: Scored }
  | { kind: 'pending'; reason: 'unexplained' | 'low-margin'; ranked: Scored[] }
  | { kind: 'ask'; ranked: Scored[] };
export class Decoder {
  constructor(cfg?: Partial<DecoderConfig>);
  readonly state: GameState; rotation: Rotation; pendingCount: number;
  calibrate(lp: LogProbs): { rotation: Rotation; disagreeing: number[]; ok: boolean };  // ok when best rotation has ≤ disagreeMax disagreeing squares vs START_BOARD
  step(lp: LogProbs): Outcome;      // applies accepted moves to state, updates rotation on accept
  accept(scored: Scored): void;     // user chose from ranked
  fixLast(uci: string[]): void;     // replace last accepted ply(s)
}
```
Step algorithm: generate tiers `none, legal, undo1, undo2, twoply` (plus `illegal` only when `pendingCount ≥ 1`); `scoreAll`; best `b`, runner-up `r`. If `b.score < acceptMin`: if `disagreeing(state.board, lp at best rotation).length > disagreeMax` → pending 'unexplained', else 'nochange'. Else if `b.score - r.score < marginMin` → pending 'low-margin'. Else accept. Pending increments `pendingCount`; when it reaches `pendingMax` return `ask` with the top 5. Accept or nochange resets `pendingCount`.

- [ ] **Step 1: Write failing tests** using `synthReading`:
  - `replays a 20-ply PGN with clean readings, every move accepted`
  - `rotation flip mid-game is still decoded` (Review Focus 1: ply 7's reading rotated by 2)
  - `missed frame recovers two plies via twoply` (Review Focus 2)
  - `lifted piece is pending then the move decodes next frame` (Review Focus 3: reading with e2 empty and e4 empty → pending 'unexplained'; next reading e2e4 → move)
  - `illegal move is accepted after pending and later legal moves still decode` (Review Focus 4: Ke1-e3 reading twice → second step returns move with tier illegal; then a legal black move decodes)
  - `noisy readings with 5% type confusion over 40 plies produce zero silent errors` (noise sampled from a fixed seed; prompts counted and asserted ≤ 2)
  - `promotion with uncertain type defaults to queen` (reading with equal probs over wQ/wR/wB/wN on the promotion square)
  - `calibrate returns rotation 2 and ok for a rotated start reading`
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** Promotion rule: among promotion candidates with equal scores within 0.1, prefer `q`.
- [ ] **Step 4: Run** → PASS. **Step 5: Commit** `feat(web): decoder state machine`

---

### Task 9: Corpus benchmark (gate G2)

**Files:**
- Create: `web/scripts/bench.ts`, `web/scripts/dump_onnx.ts`
- Modify: `eval/RESULTS.md`

**Interfaces:**
- `npm run bench -- --corpus ../eval/corpus --model lite [--drop 0.1] [--frames 1]` runs `Decoder` over each game's readings in ply order, compares accepted moves against the PGN, prints per game: plies, accepted-correct, accepted-wrong (silent), pending, ask, per-tier counts, and appends a dated table to `eval/RESULTS.md`. `--drop` removes that fraction of readings at random (seeded) to exercise two-ply.
- `dump_onnx.ts --corpus <game> --onnx <path> --out readings/lite-onnx` writes readings with onnxruntime-node so the benchmark runs on the shipped artifact; the preprocessing must match `eval/dump_probs.py` (resize, normalisation constants copied from the repo and listed in `eval/README.md`).

- [ ] **Step 1: Implement `bench.ts`** (no unit test; its output is the deliverable). Use `tsx`.
- [ ] **Step 2: Run** on PyTorch readings and on ONNX readings; both tables into `RESULTS.md`.
- [ ] **Step 3: Tune** `PRIORS`, `acceptMin`, `marginMin`, `floor` only via `DEFAULT_CONFIG`; record each run. Decide G2.
- [ ] **Step 4: Commit** `feat(web): corpus benchmark and results`

---

### Task 10: PGN export

**Files:**
- Create: `web/src/pgn.ts`
- Test: `web/test/pgn.test.ts`

**Interfaces (produces):**
```ts
export function toPgn(s: GameState, headers: Record<string,string>): { pgn: string; verifiedPlies: number; illegalAt: number | null }
```
Movetext in SAN via chess.js up to the first illegal move; at that ply append `{ illegal move <uci> played; moves after this point are not recorded }` and stop. Headers always include `Event`, `Date`, `Result "*"`, `Annotator "chess_daily"`.

- [ ] **Step 1: Write failing tests** `legal game round-trips through chess.js loadPgn`, `illegal move truncates with comment and reports illegalAt` (Review Focus 4).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(web): PGN export`

---

### Task 11: Homography and per-square energy

**Files:**
- Create: `web/src/gray.ts`, `web/src/homography.ts`
- Test: `web/test/homography.test.ts`

**Interfaces (produces):**
```ts
export interface Gray { w: number; h: number; data: Float32Array }          // 0..1
export function toGray(img: ImageData, w: number, h: number): Gray;         // area-average downscale
export interface Pt { x: number; y: number }
export type Corners = [Pt, Pt, Pt, Pt];                                       // a1, h1, h8, a8 in image pixels
export function homography(c: Corners): Float64Array;                        // 3x3, board unit square -> image
export function squareQuad(H: Float64Array, square: number): [Pt, Pt, Pt, Pt];
export function cropRect(c: Corners, marginFrac: number): { x: number; y: number; w: number; h: number };  // square, centred on the board
export function squareEnergy(prev: Gray, cur: Gray, H: Float64Array, cropOrigin: Pt, scale: number): Float32Array; // 64 values, mean |Δ| after per-frame mean-brightness normalisation
export function globalShift(ref: Gray, cur: Gray): { dx: number; dy: number; confidence: number };  // phase correlation on 64x64
```

- [ ] **Step 1: Write failing tests** `homography maps unit corners back to the given corners`, `squareQuad(H, sq('a1')) lies at the a1 corner`, `squareEnergy flags only the two squares changed in a synthetic board image`, `globalShift recovers a 3px shift of a synthetic pattern` (Review Focus 5 primitive).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (DLT with a 8x8 linear solve; no library).
- [ ] **Step 4: Run** → PASS. **Step 5: Commit** `feat(web): homography, per-square energy, shift detection`

---

### Task 12: Capture and stability

**Files:**
- Create: `web/src/capture.ts`
- Test: `web/test/capture.test.ts`

**Interfaces (produces):**
```ts
export interface CaptureConfig { stableMs: number; stableDiff: number; changeMin: number; shiftPx: number; maxFramesPerMove: number }  // 400, 0.015, 0.06, 4, 3
export interface StableFrame { seq: number; at: number; crop: Blob; gray: Gray; energy: Float32Array }
export type CaptureEvent = { kind: 'stable'; frame: StableFrame } | { kind: 'moving' } | { kind: 'bumped'; dx: number; dy: number };
export class Capture {
  constructor(video: HTMLVideoElement, cfg?: Partial<CaptureConfig>);
  start(): Promise<void>;     // getUserMedia facingMode 'environment', ideal 1920x1080; applyConstraints exposureMode 'manual' if supported; requests Screen Wake Lock
  setCorners(c: Corners): void;
  markAccepted(frame: StableFrame): void;   // becomes the reference for change and shift detection
  on(cb: (e: CaptureEvent) => void): void;
  stop(): void;
}
export class StabilityDetector {  // pure, testable: feed grays with timestamps
  constructor(cfg: CaptureConfig);
  push(g: Gray, at: number): 'moving' | 'stable' | 'settled';  // 'settled' fires once per stable period
}
```
Rules: frame diff = mean |Δ| of 64x64 grey; moving when > `stableDiff`; settled after `stableMs` below it; on settle, if `max(squareEnergy vs accepted) < changeMin` the frame is dropped silently; `globalShift` confidence > 0.5 and `|d| > shiftPx` → `bumped`.

- [ ] **Step 1: Write failing tests** for `StabilityDetector` with synthetic grays: `settles once after 400ms of low diff`, `does not settle while diff is high`, `re-settles only after moving again`; for the drop rule `frame with uniform brightness change is dropped` (energy normalisation); and for bump detection `a reference shifted by 6px emits bumped instead of stable` (Review Focus 5).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** `Capture` uses `requestVideoFrameCallback` where available, else `requestAnimationFrame`.
- [ ] **Step 4: Run** → PASS. **Step 5: Commit** `feat(web): capture, stability and bump detection`

---

### Task 13: Recognizer

**Files:**
- Create: `web/src/recognizer.ts`, `web/src/worker/onnx.worker.ts`
- Test: `web/test/recognizer.test.ts`

**Interfaces (produces):**
```ts
export interface Recognizer { read(crop: Blob): Promise<Reading>; ready(): Promise<void> }
export class OnnxRecognizer implements Recognizer { constructor(modelUrl: string, providers?: ('webgpu'|'wasm')[]) }   // runs in a Web Worker; caches the model via Cache API
export class RemoteRecognizer implements Recognizer { constructor(baseUrl: string) }   // POST /read, multipart 'image'
export class FileRecognizer implements Recognizer { constructor(readings: Reading[]) } // test double, returns in order
```
Preprocessing in the worker must match `eval/README.md` constants; the worker returns a `Reading` with `classes` copied from the model's metadata (export them as ONNX metadata in Task 4).

- [ ] **Step 1: Write failing test** `RemoteRecognizer posts multipart and parses a Reading` (mock fetch), `FileRecognizer returns readings in order`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Manual check:** `OnnxRecognizer` in the spike page reads one corpus photo; argmax matches the Task 4 parity run.
- [ ] **Step 6: Commit** `feat(web): on-device and remote recognizers`

---

### Task 14: App shell and session flow

**Files:**
- Create: `web/src/app.ts`, `web/src/ui/{setup,board,moves,fix}.ts`, `web/src/queue.ts`
- Modify: `web/src/main.ts`, `web/index.html`

**Interfaces:**
- `queue.ts`: `class FrameQueue { push(frame: StableFrame): void; }` runs `recognizer.read` with concurrency 1 in `seq` order, averages up to `maxFramesPerMove` readings per stable period with `meanLogProbs`, then calls `decoder.step` strictly in order.
- Session flow: (1) camera + framing guide; (2) four corner taps a1, h1, h8, a8 → `setCorners`; (3) start check: read one frame, `decoder.calibrate`; green when `ok`, red with the disagreeing squares highlighted otherwise; (4) tracking: chessground mirrors `decoder.state`, move list updates, `ask` opens the fix sheet with the top 5 candidates as buttons plus "undo last"; `bumped` opens the re-frame prompt; (5) export: copy PGN, open on lichess.org/paste.
- Opt-in toggle "save uncertain frames" stores the crop in IndexedDB only on `pending`/`ask`.

- [ ] **Step 1: Implement `queue.ts`** with a test `frames are decoded in seq order even when reads resolve out of order` (FileRecognizer with delayed promises).
- [ ] **Step 2: Implement the UI** (no tests; vanilla DOM, one file per screen).
- [ ] **Step 3: End-to-end on the phone** with a scripted 10-ply game including a capture, castling, a takeback, and one deliberately skipped frame: PGN matches and opens on Lichess. Record the device and timings in `RESULTS.md`.
- [ ] **Step 4: Commit** `feat(web): session flow, fix sheet, PGN export`

---

### Task 15: Eval bar

**Files:**
- Create: `web/src/engine.ts`, `web/src/ui/evalbar.ts`
- Test: `web/test/engine.test.ts`

**Interfaces (produces):**
```ts
export class Engine { constructor(workerUrl: string); evaluate(fen: string, movetimeMs: number): Promise<{ cp?: number; mate?: number }>; stop(): void; dispose(): void }
```
The worker is created when the bar is first shown and disposed when hidden; `movetimeMs = 800`; hidden by default; a new accepted position cancels the running search.

- [ ] **Step 1: Write failing test** `parses "info ... score cp 35" and "score mate -2" lines into the result` (feed UCI text to the parser function `parseScore(line: string)`).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(web): hidden eval bar with Stockfish worker`

---

### Task 16: Deploy the static app

**Files:**
- Create: `web/public/sw.js`, `.github/workflows/pages.yml` or EdgeOne Pages config as the platform requires
- Modify: `README.md`

- [ ] **Step 1: Model hosting.** Check the EdgeOne Pages per-file limit against the chosen ONNX size. If it fits, serve from `web/public/models/`. If not, **stop and ask the user** before creating a COS bucket; the bucket needs CORS for the Pages origin.
- [ ] **Step 2: Service worker** caches the model and app shell on first load (Cache API, versioned by file hash).
- [ ] **Step 3: Deploy** to the existing free EdgeOne Pages zone under a new `chess` subdomain. **DNS record creation needs explicit approval from the user** before it is made; existing records stay untouched.
- [ ] **Step 4: Verify** on the phone over mobile data: first load downloads the model once; airplane mode afterwards still runs a read.
- [ ] **Step 5: Commit** `chore: Pages deploy and model caching`

---

### Task 17: Server path (only if G1 fails)

**Files:**
- Create: `server/app.py`, `server/tests/test_app.py`, `server/chess-api.service`, `server/Caddyfile`

**Interfaces:**
- `POST /read?model=lite|large` multipart `image` → `Reading` JSON. One inference worker behind an `asyncio.Semaphore(1)`; `torch.set_num_threads(2)`; the large model is loaded in a separate process spawned on demand and exits after 10 minutes idle; images are held in memory only.

- [ ] **Step 1: Write failing test** with FastAPI `TestClient`: `read returns a Reading with 64 rows` using a stub model.
- [ ] **Step 2: Implement.** **Step 3: Run** → PASS.
- [ ] **Step 4: Harden before exposing, each with explicit user approval:** restrict SSH in the Lighthouse firewall to the user's address range (keep the console web terminal as the fallback, since mobile and home connections change address), `PermitRootLogin prohibit-password`, key-only auth. Then run the service as an unprivileged user under systemd with `MemoryMax=2G`, behind Caddy with automatic TLS, open 443 only, then add the `chess-api` A record.
- [ ] **Step 5: Commit** `feat(server): recognizer endpoint`

---

### Task 18: Per-session adaptation experiment (only if G2 fails on type accuracy)

**Files:**
- Create: `eval/adapt.py`

- [ ] **Step 1:** From each corpus game's start reading, take the 64 query embeddings as labelled prototypes (32 known pieces, 32 empties). For later plies, classify each square by cosine nearest prototype and blend with the model's probabilities (`p = 0.5 * model + 0.5 * prototype_softmax`).
- [ ] **Step 2:** Re-run `metrics.py` on the blended readings; record type accuracy before and after in `RESULTS.md`.
- [ ] **Step 3:** If it helps by ≥ 5 points, port the blend into `web/src/adapt.ts` behind a flag and re-run the benchmark (Task 9).
