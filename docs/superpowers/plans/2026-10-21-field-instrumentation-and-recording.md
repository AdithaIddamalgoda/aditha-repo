# Field Instrumentation and Session Recording Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop camera movement or any other change of scene from ever producing a move, then make every field session produce the evidence needed to tune the capture pipeline (what the model saw, what it answered, what the decoder did, and how long each stage took).

**Architecture:** The decoder gains a residual gate: a candidate is accepted only when the rest of the reading agrees with the candidate's board, so a shifted or re-cropped scene can never be explained by a lucky legal move. Camera movement, from the bump detector, the phone's motion sensors, or a scene-change residual, pauses decoding until one settled frame agrees with the tracked position again. A pure reading-sanity check (both kings visible, no pieces appearing from nowhere) runs before the decoder and turns a bad frame into a retake after one second instead of a pending count. A ring-buffer debug log and a HUD expose every capture gate live. With an opt-in toggle, the server keeps each crop it receives, the reading it returned, the client's event log, the operator's "mark" taps and the confirmed PGN under a session directory; an import script turns a recorded session into the existing corpus layout so `bench.ts` and `metrics.py` run unchanged.

**Tech Stack:** Existing web app (vanilla TypeScript, Vite, vitest), existing FastAPI server (`server/app.py`), existing `eval/` Python 3.12 via uv with `python-chess`. No new runtime dependency.

**Spec:** `docs/superpowers/research/2026-10-21-capture-latency-diagnosis.md` (sections 4, 5, 9, 10, 11) and the original design in `docs/superpowers/plans/2026-10-17-chess-camera.md` (Tasks 11 to 14, 17). If the live code names differ from the interfaces quoted below, use the live names and say so in the task's commit message.

## Global Constraints

- Node 22, TypeScript `strict: true`, no UI framework; Python 3.12 via `uv` in `eval/` and `server/`.
- Square index `a1 = 0 ... h8 = 63`; canonical class order `empty, wP, wN, wB, wR, wQ, wK, bP, bN, bB, bR, bQ, bK`; probability floor `1e-3`.
- No behaviour change to the capture thresholds (`stableDiff`, `stableMs`, `changeMin`, `shiftPx`, `maxFramesPerMove`) or to `acceptMin`, `marginMin`, `pendingMax`, the priors. The residual gate (Task 0) is the one decoder change, and it only makes acceptance stricter. Measuring comes first for everything else.
- Decoder residual gate: `residualMax = 4` squares (reading disagrees with the candidate board, using the existing `disagreeP = 0.2`); `sceneChangeResidual = 12` squares on two consecutive frames pauses decoding. Motion sensor: `rotRateDegS = 30`, `accelMs2 = 1.5`, `quietMs = 1500`; absent sensors mean a no-op, never an error.
- Sanity constants: `kingMinP = 0.5`, `totalTolerance = 1` (argmax-occupied squares may exceed the tracked count by at most 1). Retake constants: `retakeMs = 1000`, `retakeMax = 3` per stable period. Debug log capacity `2000` events; `frame` events sampled every 5th video frame; event flush to the server every `30 s` and at session end.
- Images are stored only when the operator turns on "Record this session" and the server holds a matching `CHESS_RECORD_KEY`. Storage root `CHESS_DATA_DIR`, default `server/data`. Recording stops silently when free space is under 1 GB. Nothing is stored on the phone.
- No Tencent, DNS, or Google change in any task. Every measurement goes into `eval/RESULTS.md` with date, device, build hash, and command.

## Review Focus

0. The phone is picked up, moved, and put back mid-game. Expected: no move is accepted while it moves or afterwards; the first still frame is checked against the tracked position; decoding resumes with no prompt when it agrees, else the re-frame prompt opens. Tests in Task 0 (residual gate) and Task 1 (pause and resync).
1. A king hidden behind a taller piece from the camera's side, where the recognizer still puts 0.5 or more on the king class at that square. Expected: the frame passes sanity; no retake, no prompt. Test in Task 2.
2. A capture, so the reading has one piece fewer than the tracked board. Expected: sanity passes, because pieces may vanish, never appear. Test in Task 2.
3. The server is unreachable for one read mid-game. Expected: the queue logs the error, requests a retake, and decodes the next frame in order; the app never stalls. Test in Task 3.
4. The recording toggle is on but the server key is missing or wrong. Expected: recognition works exactly as before, nothing is stored, and the HUD shows recording off. Test in Task 5.
5. The operator taps "mark" fewer times than there are plies in the PGN. Expected: the importer labels nothing it cannot justify, reports the mismatch, and still writes the frames and readings. Test in Task 6.

## Before Task 0

Answer the eight factual questions in the brief's section 6 (deployed build hash, live threshold values, how the motion diff and `settled` work, when `decoder.step` runs, what the heatmap shows, what is uploaded and the model input size, server cores and ms per read, corpus state) in `eval/RESULTS.md` under a dated heading. Where a live value differs from this plan's assumptions, say so there and in the affected task's commit message.

## Task dependency map

- Task 0 first; Task 1 needs Task 0 (`check` and the residual). Nothing else may start before Task 0 is merged.
- Task 2 → Task 3 (sanity feeds retake).
- Task 4 is independent; Task 5 needs Task 4 (it uploads the log).
- Task 6 needs Task 5's on-disk layout only.
- Task 7 is the measurement run; needs Tasks 0 to 5 deployed.

---

### Task 0: Residual gate in the decoder

**Files:**
- Modify: `web/src/decoder.ts` (`DecoderConfig`, `DEFAULT_CONFIG`, `step`), `web/src/score.ts` if `disagreeing` needs a board argument
- Test: `web/test/decoder.test.ts`

**Interfaces:**
- Consumes: `disagreeing(board: Board, lp: LogProbs): number[]` from `score.ts` (squares where the reading's argmax differs from `board` with probability at least `disagreeP`); `Scored` with its rotation; `synthReading` from `web/test/synth.ts`.
- Produces:
```ts
// DecoderConfig additions
residualMax: number;             // 4
// Outcome additions: every outcome carries the residual of the frame against the board it was judged on
//   move:     residual = disagreeing(candidate.board, lp at the winning rotation).length
//   nochange: residual = disagreeing(state.board, lp at the current rotation).length
//   pending:  residual as for the best candidate; reason 'unexplained' when residual > residualMax
export interface CheckResult { ok: boolean; residual: number; rotation: Rotation }
// Decoder addition, used by Task 1 for the resync and by the start check:
check(lp: LogProbs): CheckResult;   // best of four rotations against the current tracked board; ok when residual <= residualMax
```
- Step order after this task: generate, `scoreAll`, best `b`, runner-up `r`; compute `residual_b = disagreeing(b.board, lp_rot(b)).length`; **if `residual_b > residualMax` → pending 'unexplained'** (this check runs first, on every branch); else the existing rules (`acceptMin`, then `marginMin`, then accept). `pendingMax` and `ask` unchanged. The start check `calibrate` becomes `check` against `START_BOARD`.

- [ ] **Step 1: Quote the live step order** of `Decoder.step` in `eval/RESULTS.md` under a dated heading, two to five lines, so the mechanism in the brief's section 11 is confirmed or corrected before changing it.
- [ ] **Step 2: Write the failing tests** in `web/test/decoder.test.ts`:
  - `a frame that disagrees on ten squares is pending even when a legal move explains two of them` (state after 1. e4; reading = board after 1. e4 e5 with ten other squares set to a wrong piece at p 0.9; expect `kind: 'pending'`, `reason: 'unexplained'`, `residual >= 10`, `state.board` unchanged).
  - `a reading of the board shifted by one file is pending, not a move` (reading built from the tracked board with every piece moved one file left; expect pending and board unchanged).
  - `three shifted frames in a row produce ask, never a move` (`pendingMax` frames; expect `kind: 'ask'` and `state.history` unchanged).
  - `a clean reading with the move is still accepted and reports residual 0` (regression).
  - `check returns the rotation that agrees` (reading rotated 180 degrees of the tracked board → `ok` true, `rotation` 2, `residual` 0).
- [ ] **Step 3: Run** `cd web && npx vitest run test/decoder.test.ts` → the five new tests FAIL, existing ones PASS.
- [ ] **Step 4: Implement** the residual, `residualMax`, the new step order, and `check`.
- [ ] **Step 5: Run** `npx vitest run` → all PASS, including every pre-existing decoder test (Review Focus 1 to 4 of the original plan must still hold: the two-ply recovery, the lifted piece, the illegal move after pending).
- [ ] **Step 6: Commit** `fix(web): decoder never accepts a move on a frame that disagrees elsewhere`

---

### Task 1: Camera movement pauses decoding until a resync

**Files:**
- Create: `web/src/motion.ts`
- Modify: `web/src/queue.ts`, `web/src/app.ts`, `web/src/ui/board.ts` or the tracking screen file (banner and Undo button)
- Test: `web/test/motion.test.ts`, `web/test/queue.test.ts`

**Interfaces:**
- Consumes: `Decoder.check` and the per-outcome `residual` (Task 0); `CaptureEvent` `bumped`; `Capture.markAccepted`.
- Produces:
```ts
// motion.ts
export interface MotionConfig { rotRateDegS: number; accelMs2: number; quietMs: number }   // 30, 1.5, 1500
export interface MotionSample { t: number; rot: number; accel: number }                     // max abs rotationRate component (deg/s), |acceleration| without gravity (m/s^2)
export class MotionClassifier {            // pure
  constructor(cfg: MotionConfig);
  push(s: MotionSample): 'moving' | 'still' | 'settled';   // 'settled' once, after quietMs below both thresholds following a 'moving'
  // 'moving' needs sustained motion: at least 3 consecutive samples above a threshold spanning >= 300 ms; a single spike (a tap on the
  // clamped phone) is 'still'. MotionSensor also ignores samples for 500 ms after any touchstart/pointerdown on the page.
}
export class MotionSensor {               // wraps window 'devicemotion'; no-op when the event or its fields are unavailable
  constructor(cfg?: MotionConfig);
  start(): void; stop(): void;
  on(cb: (e: { kind: 'camera-moved' } | { kind: 'camera-still' }) => void): void;
}
// queue.ts
export type QueueState = 'tracking' | 'paused';
pause(cause: 'bumped' | 'sensor' | 'scene'): void;   // drops every frame until resumed; emits {kind:'paused', cause} to the outcome callback
// resync rule: while paused and after 'camera-still' (or at once for 'scene'), each settled frame is read and passed to decoder.check;
//   ok -> decoder.rotation = result.rotation, capture.markAccepted(frame), state 'tracking', emit {kind:'resumed', residual, rotation}
//   not ok -> emit {kind:'reframe', residual}; stay paused
// scene rule: two consecutive 'tracking' outcomes with residual > sceneChangeResidual (12) -> pause('scene')
// rotation rule (research note 2026-10-22, section 3): when a 'tracking' outcome is pending 'unexplained' under the current rotation,
//   run decoder.check(lp); if it is ok at another rotation, set decoder.rotation to it, emit {kind:'rotated', from, to, residual},
//   and treat the frame as nochange (markAccepted). A pause's resync and the bump refit call the same path.
// undo: the operator's "Undo last move" walks decoder.state.history to any depth; it is not limited by the undo1/undo2 tiers.
```
- `app.ts`: `bumped` → `queue.pause('bumped')`; `camera-moved` → `queue.pause('sensor')`; banner "Camera moved. Keep it still." while paused; `reframe` opens the existing re-frame prompt (corner taps today, the nudge UI once the board-detection plan lands). An "Undo last move" button is always visible on the tracking screen and calls the same undo path the fix sheet's "undo last" uses; each tap undoes one more ply.

- [ ] **Step 1: Write the failing tests** in `web/test/motion.test.ts`: `a rotation burst then quiet yields moving then settled after quietMs`, `samples below both thresholds never yield moving`, `acceleration alone above accelMs2 yields moving`, `a single 80 ms spike is still, not moving` (review 2026-10-22, A2: a Mark tap must not pause decoding), `samples within 500 ms of a touch are ignored` (MotionSensor with an injected touch timestamp).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement `MotionClassifier` and `MotionSensor`.** **Step 4: Run** → PASS.
- [ ] **Step 5: Write the failing queue tests**:
  - `paused queue drops frames and steps nothing` (spy on `decoder.step`).
  - `resumes only after a frame passes check, and adopts its rotation` (FileRecognizer: one disagreeing reading, then one rotated-180 agreeing reading → `reframe` then `resumed` with `rotation` 2; `decoder.step` not called for either).
  - `two consecutive high-residual frames pause the queue with cause scene` (Review Focus 0: two readings of a shifted board → `paused`, no `move`).
  - `a bumped event pauses before the next frame is decoded`.
  - `a reading rotated 180 degrees mid-game switches the rotation and commits nothing` (state after 1. e4 e5; reading = that board rotated 180 → outcome `rotated` with `to` 2, `decoder.step` history unchanged; the next reading at rotation 2 with 2. Nf3 → `move`).
  - `undo walks back five plies` (five accepted moves, five undo calls → start position).
- [ ] **Step 6: Run** → FAIL. **Step 7: Implement** in `queue.ts` and wire `app.ts`, the banner, and the Undo button. **Step 8: Run** `npx vitest run` → all PASS.
- [ ] **Step 9: Phone check**: pick the phone up mid-game and put it back; the banner shows, no move appears, tracking resumes without a prompt when the framing is the same. Slide the tripod 10 cm: the re-frame prompt opens. Record both in `eval/RESULTS.md`.
- [ ] **Step 10: Commit** `feat(web): camera movement pauses decoding until the board agrees again`

---

### Task 2: Reading sanity check

**Files:**
- Create: `web/src/sanity.ts`
- Modify: `web/src/queue.ts` (run the check before `decoder.step`)
- Test: `web/test/sanity.test.ts`, `web/test/queue.test.ts`

**Interfaces:**
- Consumes: `LogProbs`, `Board`, `PieceClass` from `web/src/types.ts`; `synthReading` from `web/test/synth.ts`; `Decoder.state.board` from `web/src/decoder.ts`.
- Produces:
```ts
export interface SanityConfig { kingMinP: number; totalTolerance: number }         // 0.5, 1
export const DEFAULT_SANITY: SanityConfig;
export type SanityReason = 'no-wK' | 'no-bK' | 'too-many-pieces';
export interface Sanity { ok: boolean; reasons: SanityReason[]; kingP: { w: number; b: number }; expectedTotal: number; trackedTotal: number }
export function checkReading(lp: LogProbs, board: Board, cfg?: SanityConfig): Sanity;
// kingP.w = max over squares of exp(lp[s][wK]); 'no-wK' when below kingMinP; same for black.
// expectedTotal = number of squares whose argmax class is not empty (counting argmax, not summed probability:
// a 0.9-confidence reading spreads about 0.1 over the 12 piece classes on every empty square, which would sum to
// three phantom pieces); trackedTotal = occupied squares of board;
// 'too-many-pieces' when expectedTotal > trackedTotal + totalTolerance. Rotation-invariant by construction.
// queue.ts: new outcome kind emitted to the app's outcome callback and the debug log:
export type QueueOutcome = Outcome | { kind: 'badframe'; seq: number; sanity: Sanity; forced: boolean };   // forced: decoder was stepped anyway (Task 3)
```

- [ ] **Step 1: Write the failing tests** in `web/test/sanity.test.ts`:
  - `passes on a clean start reading` (`synthReading(START_BOARD, 0.9)` → `ok` true, `reasons` empty, `kingP.w >= 0.9`).
  - `flags no-wK when the white king probability is below 0.5 everywhere` (noise entry setting e1 to `{cls:'empty', p:0.6}` → `reasons` contains `'no-wK'`, `ok` false).
  - `passes when the king is seen at exactly 0.5` (Review Focus 1: e1 `wK` at 0.5 → `ok` true).
  - `passes after a capture` (Review Focus 2: board after exd5, reading with 31 pieces, tracked board with 32 → `ok` true).
  - `tolerates one phantom piece` (START_BOARD tracked, reading puts `wP` 0.9 on e4 and keeps e2 → `ok` true).
  - `flags too-many-pieces when two pieces appear from nowhere` (same with `wP` 0.9 on e4 and d4 → `reasons` contains `'too-many-pieces'`).
- [ ] **Step 2: Run** `cd web && npx vitest run test/sanity.test.ts` → FAIL with "checkReading is not a function".
- [ ] **Step 3: Implement `checkReading`** in `web/src/sanity.ts` as specified in the Interfaces block.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Write the failing queue test** in `web/test/queue.test.ts`: `emits badframe and does not step the decoder on a reading with no white king` (FileRecognizer returning that reading; spy on `decoder.step`; the outcome callback receives `{kind:'badframe'}`; `decoder.pendingCount` unchanged).
- [ ] **Step 6: Run** → FAIL. **Step 7: Implement** in `queue.ts`: after averaging and before `decoder.step`, call `checkReading(lp, decoder.state.board)`; on failure emit `badframe` and skip the step.
- [ ] **Step 8: Run** `npx vitest run` → all PASS.
- [ ] **Step 9: Commit** `feat(web): reading sanity check before the decoder`

---

### Task 3: Retake timer

**Files:**
- Modify: `web/src/capture.ts` (`CaptureConfig`, `Capture`, `StabilityDetector`), `web/src/queue.ts`
- Test: `web/test/capture.test.ts`, `web/test/queue.test.ts`

**Interfaces:**
- Consumes: `QueueOutcome` from Task 2; `CaptureEvent`, `StableFrame` from `capture.ts`.
- Produces:
```ts
// CaptureConfig additions
retakeMs: number; retakeMax: number;            // 1000, 3
// Capture addition
requestRetake(): void;   // after retakeMs, if no 'moving' since the request, emits {kind:'stable', frame} from the current video frame with a fresh seq;
                         // at most retakeMax retakes per stable period; further requests are ignored; a 'moving' event cancels a pending retake
// CaptureEvent addition
| { kind: 'retake'; n: number }                 // emitted when the retake fires, n = 1..retakeMax within the period
```
- `queue.ts` calls `capture.requestRetake()` when the outcome is `badframe` or `pending`, and when `recognizer.read` rejects (the rejection is logged, the frame is dropped, the next frame decodes in order).
- **Interim hand gate** (roadmap note 2026-10-22, section 4): on settle, if at least `occludedSquares = 8` entries of `StableFrame.energy` are at or above `occludedEnergy = 0.06`, `Capture` emits `{kind:'occluded', count}` instead of `stable`, does not read, and arms the retake. Measured on game 36: flags 36 of 39 hand frames and 0 of 40 clean frames. Replaced by the stage 4 classifier, never tuned by hand.
- Sanity must never stop decoding for good: `queue.ts` counts consecutive `badframe` outcomes; when the count reaches `retakeMax`, the next failing reading is passed to `decoder.step` anyway (the decoder cannot remove a king, so this is safe) and the outcome is emitted with `forced: true`. The counter resets on any `move` or `nochange`.

- [ ] **Step 1: Write the failing tests** in `web/test/capture.test.ts` using the pure detector plus a fake clock (inject `now()` and `setTimeout` through the constructor if the live class does not already):
  - `retake fires after retakeMs when the scene stays still`.
  - `a moving event cancels a pending retake`.
  - `at most retakeMax retakes per stable period, counter resets after the next settle`.
  - `a settled frame with 8 squares at 0.07 is occluded and not read; with 7 it is stable` (interim hand gate).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** in `capture.ts`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Write the failing queue tests**: `requests a retake on badframe`, `requests a retake on pending`, `a rejected read is logged, dropped, and the next frame still decodes in seq order` (Review Focus 3: FileRecognizer whose second promise rejects), `after retakeMax consecutive badframes the decoder is stepped and the outcome is forced` (four readings with no white king: `decoder.step` called once, on the fourth).
- [ ] **Step 6: Run** → FAIL. **Step 7: Implement** in `queue.ts`. **Step 8: Run** `npx vitest run` → all PASS.
- [ ] **Step 9: Commit** `feat(web): retake a frame after a bad or pending read`

---

### Task 4: Debug log, HUD, server timing

**Files:**
- Create: `web/src/debuglog.ts`, `web/src/ui/hud.ts`
- Modify: `web/src/capture.ts` (emit per-frame diagnostics), `web/src/queue.ts`, `web/src/recognizer.ts` (`RemoteRecognizer` timing), `web/src/app.ts` (wire `?debug=1`)
- Modify: `server/app.py` (`Server-Timing` header)
- Test: `web/test/debuglog.test.ts`, `web/test/recognizer.test.ts`, `server/tests/test_app.py`

**Interfaces:**
- Consumes: `QueueOutcome`, `Sanity` (Task 2); `CaptureEvent` including `retake` (Task 3); `Reading.ms` from the contract.
- Produces:
```ts
export type DebugEvent =
  | { kind: 'frame';    t: number; meanDiff: number; state: 'moving' | 'stable' | 'settled' }
  | { kind: 'settle';   t: number; seq: number; maxEnergy: number; energy: number[]; dropped: boolean }
  | { kind: 'read';     t: number; seq: number; cropW: number; cropH: number; jpegBytes: number; uploadMs: number; serverMs: number; totalMs: number; error?: string }
  | { kind: 'decode';   t: number; seq: number; outcome: 'move' | 'nochange' | 'pending' | 'ask'; move?: string; tier?: Tier; score: number; margin: number; residual: number; rotation: Rotation; pendingCount: number }   // move in UCI when outcome is 'move'
  | { kind: 'paused';   t: number; cause: 'bumped' | 'sensor' | 'scene' }
  | { kind: 'resumed';  t: number; residual: number; rotation: Rotation }
  | { kind: 'rotated';  t: number; from: Rotation; to: Rotation; residual: number }
  | { kind: 'phase';    t: number; phase: 'finding' | 'tracking' | 'paused' | 'asking' | 'lost' }
  | { kind: 'answer';   t: number; what: 'candidate' | 'nothing' | 'manual' | 'undo'; move?: string }   // every fix-sheet and undo action, move in UCI
  | { kind: 'badframe'; t: number; seq: number; reasons: SanityReason[]; kingP: { w: number; b: number }; forced: boolean }
  | { kind: 'retake';   t: number; n: number }
  | { kind: 'occluded'; t: number; seq: number; count: number }
  | { kind: 'user';     t: number; note: string };
export class DebugLog {
  constructor(capacity?: number);                 // 2000
  push(e: DebugEvent): void;
  snapshot(): DebugEvent[];                       // everything retained, oldest first
  drain(): DebugEvent[];                          // events pushed since the last drain (for upload), independent of eviction
  toBlob(): Blob;                                 // JSON array of snapshot()
}
```
- `t` is `performance.now()` plus a session epoch so events sort across reloads: `t = Date.now()` at push.
- `meta.buildHash` must be a clean commit hash; the app refuses to start a *recording* session from a `-dirty` build and says so in the HUD.
- `Capture` gains a diagnostics callback `onDiag(cb: (e: DebugEvent) => void)` used for `frame` (every 5th frame), `settle`, `retake`; `Capture` must also report dropped frames through `settle` with `dropped: true`.
- `RemoteRecognizer.read` records `fetch` start, headers-received, and end; `serverMs` is parsed from the `Server-Timing` header (`model;dur=`, `total;dur=`), falling back to `Reading.ms`; `uploadMs = headersReceivedAt - start - serverTotalMs`.
- `server/app.py` `/read` sets `Server-Timing: model;dur=<ms>, total;dur=<ms>` where `model` is the forward pass and `total` is request receipt to response.
- `server/app.py` creates the ORT inference session at process start (never lazily in a request), keeps it for the life of the process, and adds `cold;desc=1` to `Server-Timing` on any read that still had to create it (RESULTS 2026-10-22: 13 s first read after idle). The client sends one warm-up read of a blank 644 x 644 JPEG when a session starts and logs it as `read` with `warmup: true`.
- HUD (`ui/hud.ts`), shown only with `?debug=1`: live `meanDiff` with the `stableDiff` line; the 8x8 energy heatmap with the `changeMin` value marked on its colour scale; the last three `decode` or `badframe` lines with tier, score, margin; last `totalMs`; a recording indicator (Task 5); a "Mark" button that pushes `{kind:'user', note:'mark'}`; a "Download log" button calling `toBlob()`.

- [ ] **Step 1: Write the failing tests** `DebugLog keeps only the last 2000 events`, `drain returns only events pushed since the previous drain`, `toBlob is a JSON array in push order`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement `DebugLog`.** **Step 4: Run** → PASS.
- [ ] **Step 5: Write the failing recognizer test** `RemoteRecognizer reports serverMs from Server-Timing and uploadMs from the fetch timing` (mock `fetch` with a `Server-Timing` header and a fake clock).
- [ ] **Step 6: Run** → FAIL. **Step 7: Implement** the timing in `RemoteRecognizer` and the `onDiag` emissions in `capture.ts` and `queue.ts`. **Step 8: Run** → PASS.
- [ ] **Step 9: Server tests** `read sets Server-Timing with model and total durations` and `the inference session exists before the first request` (stub model; assert the loader ran at app start, not in the handler). Run `cd server && uv run pytest -q` → FAIL, implement, → PASS.
- [ ] **Step 10: Implement the HUD** (`ui/hud.ts`, no test) and wire `?debug=1` in `app.ts`. Manual check on the phone: the heatmap updates when a hand passes, the `meanDiff` value moves, "Download log" saves a file.
- [ ] **Step 11: Commit** `feat: debug log, HUD and server timing`

---

### Task 5: Session recording (opt-in) on the server

**Files:**
- Modify: `server/app.py`
- Create: `server/recording.py`
- Modify: `web/src/recognizer.ts` (`RemoteRecognizer` headers), `web/src/app.ts` (session create, flush, end dialog), `web/src/ui/setup.ts` (toggle and key field)
- Test: `server/tests/test_recording.py`, `web/test/recognizer.test.ts`

**Interfaces:**
- Consumes: `DebugLog.drain()` (Task 4); existing `/read`.
- Produces, server:
```python
# server/recording.py
class SessionStore:
    def __init__(self, root: Path, record_key: str | None, min_free_bytes: int = 1 << 30): ...
    def create(self, meta: dict, key: str | None) -> tuple[str, bool]:   # (session_id, recording); recording only when key == record_key and record_key is set
    def save_read(self, session_id: str, seq: int, image: bytes, reading: dict) -> bool:  # frames/{seq:04d}.jpg, readings/{seq:04d}.json; False when not recording or low on space
    def append_events(self, session_id: str, events: list[dict]) -> int:  # events.jsonl, returns count written
    def save_pgn(self, session_id: str, pgn: str) -> None:                 # game.pgn
```
  Routes: `POST /sessions` (JSON `meta`, header `X-Record-Key`) → `{"id": str, "recording": bool}`; `POST /read` reads headers `X-Session`, `X-Seq` and, when the session is recording, calls `save_read`, setting response header `X-Recorded: 1|0`; `POST /sessions/{id}/events` (JSON array) → `{"written": int}`; `POST /sessions/{id}/pgn` (text/plain) → `204`. Session ids are `YYYYMMDD-HHMMSS-<6 random hex>`. Layout: `CHESS_DATA_DIR/sessions/<id>/{session.json, frames/, readings/, events.jsonl, game.pgn}`. `session.json` is the client's `meta` plus `created_at`, `recording`, `server_model`.
- Produces, client: `RemoteRecognizer` constructor gains `opts?: { session?: () => string | null }` and sends `X-Session` and `X-Seq` (the `StableFrame.seq`) on each read; `app.ts` posts `/sessions` at session start with `meta = { ua, buildHash, captureConfig, decoderConfig, corners, cropRect, videoW, videoH, lensLabel, recognizer: 'remote' | 'onnx', startedAt }`; flushes `debugLog.drain()` to `/sessions/{id}/events` every 30 s and on "End session"; the end dialog shows the PGN from the move list in a textarea for correction and posts it to `/sessions/{id}/pgn`. Setup screen: toggle "Record this session for tuning (saves board crops on the owner's server only)", default off, and a "Recording key" field; both persist in `localStorage`. The "Mark" button from the HUD is also shown, large, at the bottom of the tracking screen whenever recording is on.

- [ ] **Step 1: Write the failing server tests** with `TestClient` and a `tmp_path` root:
  - `create with the right key records; read stores frame and reading under the session`.
  - `create with a wrong key returns recording false and read stores nothing but still returns a Reading` (Review Focus 4).
  - `create when CHESS_RECORD_KEY is unset never records`.
  - `events append as JSONL and pgn is saved`.
  - `save_read returns False and stores nothing when free space is below the floor` (monkeypatch `shutil.disk_usage`).
- [ ] **Step 2: Run** `cd server && uv run pytest -q` → FAIL. **Step 3: Implement** `recording.py` and the routes. **Step 4: Run** → PASS.
- [ ] **Step 5: Write the failing client test** `RemoteRecognizer sends X-Session and X-Seq when a session is set` (mock `fetch`, assert headers).
- [ ] **Step 6: Run** → FAIL. **Step 7: Implement** the headers, the session create, the 30 s flush, the end dialog, the setup toggle and key field, and the recording indicator in the HUD. **Step 8: Run** `npx vitest run` → all PASS.
- [ ] **Step 9: Deploy** to the dev server with `CHESS_RECORD_KEY` set to a value the owner chooses (handed over out of band, never committed) and `CHESS_DATA_DIR` on the data disk. Confirm one recorded session appears on disk with frames, readings, events and a PGN.
- [ ] **Step 10: Commit** `feat: opt-in session recording on the server`

---

### Task 6: Import a recorded session into the corpus layout

**Files:**
- Create: `eval/import_session.py`
- Test: `eval/tests/test_import_session.py`
- Modify: `eval/corpus/README.md` (add the "record with the app" protocol as the preferred way)

**Interfaces:**
- Consumes: the session layout from Task 5; `make_corpus` conventions from `eval/make_corpus.py`.
- Produces:
```python
@dataclass
class ImportReport:
    plies: int            # from game.pgn
    marks: int            # 'user' events with note 'mark'
    frames: int           # reads found
    labelled: int         # frames given a ply index
    unlabelled: int
    warnings: list[str]

def label_frames(reads: list[dict], marks: list[float], plies: int, slack_s: float = 2.0) -> list[int | None]:
    # label = number of marks with mark_t <= read_t + slack_s; None when label > plies
def import_session(session_dir: Path, out_dir: Path, model: str = "lite") -> ImportReport:
    # writes out_dir/game.pgn, setup.json (from session.json), frames/NNNN.jpg + frames.jsonl ({seq, t, ply, outcome}),
    # plies/NNN.jpg = the last frame labelled ply NNN, readings/<model>/NNN.json = the server reading for that frame;
    # warns when marks != plies, when a ply has no frame, and when any frame is unlabelled.
```
  CLI: `uv run python import_session.py <session_dir> <out_dir> [--model lite] [--slack 2.0]`, prints the report.

- [ ] **Step 1: Write the failing tests** with a synthetic session built in `tmp_path`:
  - `labels frames by marks with slack` (reads at t = 0, 10.4, 20.4; marks at 11.5, 21.5; plies 2 → labels `[0, 1, 2]`).
  - `a retake just before the next move keeps the earlier label` (read at 18.0, mark at 21.5 → label 1).
  - `fewer marks than plies leaves later frames unlabelled and warns` (Review Focus 5: 1 mark, 2 plies → one warning naming the counts, last frames `None`).
  - `writes the plies layout make_corpus would accept` (plies/000..002.jpg exist, readings/lite/000..002.json exist, frames.jsonl has one line per read).
- [ ] **Step 2: Run** `cd eval && uv run pytest tests/test_import_session.py -q` → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Update `eval/corpus/README.md`**: the preferred protocol is now "turn on Record, tap Mark the moment each hand leaves the board, correct the PGN at End session, then run `import_session.py`"; the photo-per-ply protocol stays as the fallback.
- [ ] **Step 6: Commit** `feat(eval): import recorded sessions into the corpus layout`

---

### Task 7: First measured session and the per-ply table

**Files:**
- Modify: `eval/RESULTS.md`

No code. This is the measurement the diagnosis brief asks for; it decides the next plan.

- [ ] **Step 00: Squash versus letterbox.** On the server, read the example photo and ten source frames of recorded crops both squashed to 644 x 644 (as the client does today) and letterboxed (padded to square, board centred); table per-square max probability and argmax agreement between the two in `eval/RESULTS.md`. If letterboxing is better, the client change is the next plan's first item.
- [ ] **Step 0: Camera-move test.** Mid-game, the owner picks the phone up, waves it, and puts it back on the tripod; then, in a second game, slides the tripod 10 cm. Expected in the log: `paused`, no `decode` with outcome `move` until `resumed`, and the tracked position unchanged. Any accepted move during either test is a blocking bug: stop and report.
- [ ] **Step 1: Owner runs the protocol** from the brief, section 4: `?debug=1`, Record on, the ten-ply script `1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7`, "Mark" the moment each hand leaves, no lens covering, PGN confirmed at End session. Then once more with the players swapped.
- [ ] **Step 2: Builder imports both sessions** with `import_session.py` into `eval/corpus/session-<id>/` and commits the report output.
- [ ] **Step 3: Builder writes the per-ply table** into `eval/RESULTS.md` from `events.jsonl`: per ply, `mark t`, next `moving` t (or none), `settled` t, `maxEnergy`, dropped or read, `jpegBytes`, `uploadMs`, `serverMs`, `badframe` reasons if any, `retake` count, decode outcome, tier and `residual`, and delay from mark to decode. Also the distribution of `meanDiff` during plain hand moves versus at rest, and of `maxEnergy` on plies that were read versus dropped.
- [ ] **Step 4: Builder states which hypotheses of the brief's section 9 the table confirms**, in two or three sentences under the table, and stops. The threshold changes and the speed work are the next plan, written from this table.
- [ ] **Step 5: Commit** `docs(eval): first instrumented field session`
