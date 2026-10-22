# Capture latency and missed frames: diagnosis brief

Written 2026-10-21 by the planner, from the owner's first field report after
the server-by-default change. No fix is proposed until the evidence below is
in; this brief says what to measure, what each measurement would mean, and
which fix follows from which result. Companion to
`docs/superpowers/plans/2026-10-17-chess-camera.md` (design, Tasks 11 to 14,
17) and `docs/superpowers/HANDOVER-2026-10-21.md`.

## 1. What the owner observed

1. Recognition works and is "somewhat accurate".
2. Moves appear in the move list only after White and Black have each made
   one move. One ply alone does not show up.
3. The per-square heatmap in the UI reacts weakly or not at all to a move.
4. Covering the camera with a hand and uncovering it makes the app read the
   board again, and the moves then appear.
5. Goal: faster response, then refine into a dependable tool.

Observation 4 is the strongest clue. Covering the lens is the one event that
is guaranteed to exceed every threshold in the capture pipeline at once: the
whole-frame motion threshold, the per-square change threshold, and the
brightness normalisation. A hand moving one pawn exceeds none of them with
certainty. So the first place to look is the capture gate, not the model.

## 2. The pipeline as designed, with every gate that can stall it

Numbers are the plan's defaults. The live code may differ; the builder
confirms each in section 6.

| Stage | What must happen for the next stage to run | Default | Can it explain 2, 3 or 4? |
|---|---|---|---|
| A. Motion | mean abs diff of the whole 64x64 grey crop between consecutive video frames must exceed `stableDiff` to open a new "moving" period | 0.015 | Yes. `settled` fires once per stable period, and a new period needs a `moving` event first. If a quiet pawn move never crosses 0.015, no settle ever fires until something big (a cover) does. Explains 2, 3, 4. |
| B. Settle | diff must stay below `stableDiff` for `stableMs` | 400 ms | Adds 0.4 s. Not a stall by itself. |
| C. Change gate | `max(squareEnergy vs last accepted frame)` must exceed `changeMin` or the frame is dropped silently | 0.06 | Yes. At 64x64 a square is at most 8x8 px, and the far ranks at 45 degrees are 3 to 4 px tall. A pawn moving between two squares of similar brightness can change the mean by well under 0.06. Explains 2, 3, 4. The heatmap in the UI is probably this energy array, which is why it looks insensitive. |
| D. Averaging | the queue averages up to `maxFramesPerMove` readings "per stable period" | 3 | Possibly. If the queue waits for 3 frames or for the stable period to end before decoding, decode happens when the *next* motion starts, i.e. when the opponent reaches for a piece. That is a one-ply lag and would look like observation 2. |
| E. Upload | still capture, JPEG encode, POST to the server in Singapore | unknown; a full-resolution still is 3 to 5 MB | Latency only. On mobile data this alone can be 2 to 6 s. |
| F. Server | semaphore(1), `torch.set_num_threads(2)`, ViT-S on the Lighthouse CPU | unknown | Latency only. Probably 0.5 to 3 s per read. |
| G. Decoder | best candidate `score >= acceptMin` and margin `>= marginMin`, else pending; `ask` after `pendingMax` | 2.0 / 1.5 / 3 | Possibly. If a single ply is pending (low margin at this angle) and the next frame already shows the reply, the two-ply tier explains four squares with prior -3 and both plies land at once. Explains 2 but not 3 or 4. |

Two-ply recovery is by design, but as a safety net for a missed frame. If
every move arrives through it, a stage above G is failing on every ply.

## 3. Hypotheses, ranked

Each one is confirmed or refuted by one line of the log in section 4.

| # | Hypothesis | Explains | Confirming evidence | Refuting evidence |
|---|---|---|---|---|
| H1 | Stage A never fires `moving` for an ordinary move because `stableDiff` is measured over the whole crop, so one hand on the far side is too small a fraction of the pixels | 2, 3, 4 | Log shows no `moving` event between two plies that the owner made normally, then `moving` on the cover | `moving` and `settled` appear for every ply |
| H2 | Stage C drops the settled frame because `changeMin` is above the real per-square energy of a move at this angle and resolution | 2, 3, 4 | `settled` appears per ply, `maxEnergy` is below 0.06, frame logged as dropped | `maxEnergy` is above 0.06 on most plies |
| H3 | Stage D holds the reading until the stable period ends | 2 | Decode time stamps line up with the start of the opponent's motion, not with the settle of the mover's ply | Decode happens within one read time of the settle |
| H4 | Stages E and F together take longer than a ply, so the frame that reaches the decoder is already two plies on | 2 | `uploadMs + serverMs` is comparable to the time between plies; decoder outcome tier is `twoply` | Reads complete in under 2 s |
| H5 | Stage G: single plies are pending at this angle, the reply arrives, two-ply wins | 2 | Outcome log shows `pending` on the first frame, then `move` with tier `twoply` | First frame after a ply is `move` with tier `legal` |

H1 and H2 are not exclusive and I expect both to be partly true. They share a
cause: the thresholds were set by reasoning, not measured against this
tripod, this lens, and this light. Measuring is the fix's first step.

## 4. Instrumentation (Phase 1: evidence before fixes)

The builder adds a debug mode to the web app, switchable by a query string
such as `?debug=1`, that does two things. Nothing in it changes behaviour.

**A. Ring-buffer log** of the last 2000 events, exported as JSON from a
"Download log" button. Event kinds and fields:

```
frame     { t, meanDiff, state: 'moving'|'stable'|'settled' }      // every video frame, or every 5th if too chatty
settle    { t, seq, maxEnergy, energy[64], dropped: boolean, reason? }
read      { t, seq, cropW, cropH, jpegBytes, uploadMs, serverMs, totalMs, modelMs }
decode    { t, seq, outcome: 'move'|'nochange'|'pending'|'ask', tier?, score, margin, rotation, pendingCount }
user      { t, note }                                              // one button: "mark" (owner taps it when a hand leaves the board)
```

`serverMs` comes from a `Server-Timing` header or a field in the `Reading`
JSON (the contract already has `ms`). `uploadMs` is `fetch` start to first
byte minus `serverMs`.

**B. HUD overlay** on the camera view: current `meanDiff` with the
`stableDiff` line, the energy heatmap with `changeMin` on its colour scale,
the last three `decode` outcomes with tier and margin, and the last
`totalMs`. The owner can then see which gate is holding a frame while it
happens.

**Protocol for the owner** (ten minutes at the tripod, usual setup, no lens
covering):

1. Start a session from the initial position with `?debug=1`.
2. Play a scripted ten-ply sequence slowly: 1. e4 e5 2. Nf3 Nc6 3. Bb5 a6
   4. Ba4 Nf6 5. O-O Be7. After each hand leaves the board, tap "mark".
3. Write down, per ply, the wall-clock seconds from the hand leaving to the
   move appearing, and whether it appeared alone or together with the reply.
4. Repeat once with the players swapped so the far-side and near-side moves
   are both covered.
5. Download the log and give it to the builder; paste the per-ply times to
   the planner.

The builder then produces one table from the log: per ply, time of `mark`,
time of the next `moving`, `settled`, `maxEnergy`, dropped or read,
`uploadMs`, `serverMs`, decode outcome and tier, and the delay from `mark`
to `decode`. That table decides which hypotheses hold.

## 5. Decision table: evidence to fix

Not to be built before section 4 is done. Listed so the plan can be written
the same day the table arrives.

| If the table shows | Fix | Notes |
|---|---|---|
| H1: no `moving` between plies | Measure motion on the board region only, not the whole crop, and against a short running reference; or trigger a stable period from per-square energy as well as whole-frame diff | Keep `stableDiff` for the "hand in frame" case. Add a second, lower trigger: any square's energy against the accepted frame above a noise multiple opens a period. |
| H2: `maxEnergy` below 0.06 on real moves | Make `changeMin` adaptive: `k` times the median per-square energy between consecutive settled frames with no move (the noise floor), `k` around 3; compute energy on a 128x128 crop, not 64x64, and weight squares by their projected area so far ranks are not under-counted | The 128x128 crop already exists in the twin plan's constraints. |
| H3: decode waits for the period to end | Decode on the first settled frame; treat later frames in the same period as refinement only (average and re-decode only if the outcome changes) | Keeps the averaging benefit without the lag. |
| H4: `uploadMs` dominates | Crop to the board plus margin and resize to the model's input size on the phone before upload, JPEG quality about 85; keep the connection warm (HTTP keep-alive, a HEAD at session start); send the frame as soon as it settles, do not wait for the still if the video frame is sharp | Needs the model input size from the builder. A 448 px crop at quality 85 is about 60 to 120 KB, so upload drops from seconds to about 100 to 300 ms. |
| H4: `serverMs` dominates | Check thread count against the VM's cores, confirm fp32 ViT-S timing, try int8 dynamic quantisation on the server, confirm the model is warm and the semaphore is not queueing stale frames; drop frames older than the newest settled one if the queue is behind | Stale-frame dropping must keep decode order; drop before read, never after. |
| H5: `pending` then `twoply` | This is the decoder gate. Do not loosen `marginMin` blindly: look at which squares disagree in the pending frame. Likely the far-rank or occluded squares. This is what the twin's visibility weighting is for; it moves up the queue | Gate G2 numbers from the corpus are the right way to tune this, not field feel. |
| Nothing above: reads are fast and every ply decodes | The report is explained by the server change not being live on the phone, or by caching. Confirm the deployed build hash | Ask before anything else. |

A sensible end-to-end target, to be agreed with the owner: hand leaves the
board to the move showing on screen in 2 s on Wi-Fi and 3 s on mobile data.
Budget: settle 0.4 s, still and encode 0.2 s, upload 0.3 s, server 0.8 s,
decode and render under 0.1 s. Anything over that in one stage is where the
work goes.

## 6. Paste block for the builder

> Field report from the owner after the server-by-default change: moves show
> only after both sides have moved; the square heatmap barely reacts; covering
> and uncovering the lens forces a read. Before changing any threshold, please
> answer these and add the instrumentation below.
>
> Facts needed (with file and line where relevant):
> 1. Is `RemoteRecognizer` the default in the deployed build on the owner's
>    phone, and what is the deployed commit hash?
> 2. Current values of `stableDiff`, `stableMs`, `changeMin`, `shiftPx`,
>    `maxFramesPerMove`, `acceptMin`, `marginMin`, `pendingMax`.
> 3. In `capture.ts`: is the motion diff computed over the whole 64x64 crop or
>    the board quad only? What is the reference for the diff, the previous
>    frame or the last accepted frame? Does `settled` fire once per stable
>    period, and what re-arms it?
> 4. In `queue.ts`: does `decoder.step` run on the first settled frame, or does
>    the queue wait for `maxFramesPerMove` frames or for the stable period to
>    end?
> 5. What exactly is the heatmap in the UI: the `energy` array from
>    `squareEnergy`, the recognizer's probabilities, or something else? What
>    is its colour scale?
> 6. What does the phone send per read: resolution, JPEG quality, typical
>    bytes? What is the model's input size? Is the crop resized on the phone
>    or on the server?
> 7. Server: cores on the VM, `torch.set_num_threads`, measured ms per read
>    for Lite, whether the model is loaded at startup or on first request.
> 8. Are the two corpus games recorded with a photo per ply and PGN? Does
>    `eval/RESULTS.md` have the per-square accuracy numbers and the G2 table?
>
> Instrumentation to add (no behaviour change), as one small task with a
> commit: a `?debug=1` mode with a 2000-event ring buffer and a "Download log"
> button, event kinds `frame {t, meanDiff, state}`, `settle {t, seq,
> maxEnergy, energy[64], dropped}`, `read {t, seq, cropW, cropH, jpegBytes,
> uploadMs, serverMs, totalMs}`, `decode {t, seq, outcome, tier, score,
> margin, rotation, pendingCount}`, `user {t, note}` from a "mark" button;
> plus a HUD showing live `meanDiff` against `stableDiff`, the energy heatmap
> with `changeMin` marked on its scale, the last three decode outcomes, and
> the last `totalMs`. Return `serverMs` in the `Reading` (the `ms` field) and
> as a `Server-Timing` header. Then run the owner's ten-ply protocol and
> produce the per-ply table (mark, moving, settled, maxEnergy, dropped or
> read, uploadMs, serverMs, outcome, tier, delay to decode) into
> `eval/RESULTS.md`.

## 7. Questions for the owner

1. When Black's reply lands, do both moves appear at that moment, or does
   White's move appear earlier, at the moment Black's hand enters the frame?
   (Separates H3 from the others.)
2. Was the phone on Wi-Fi or mobile data during the test?
3. Roughly how many seconds from the hand leaving the board to the move
   appearing, when it does appear without covering the lens?
4. Which phone and browser, and is the app running as an installed web app
   or in a tab?
5. What response time would you call good enough for the club evening? The
   brief assumes 2 s on Wi-Fi, 3 s on mobile data.
6. Are the corpus games recorded? Everything after the field fix depends on
   them.

## 8. What this brief does not do

It does not change any threshold, and it does not start the twin work. The
twin's visibility weighting is the likely answer to H5 if H5 turns out to
hold, but it is a week of work and must not be started on a hunch while a
0.06 constant may be the whole story.

## 9. Update after the owner's second report (same day)

New facts from the owner:

- Covering and uncovering the lens after every ply records the moves one by
  one. So the decoder accepts single plies at this angle, and the server
  path returns usable readings.
- Phone: Redmi Note 11 Pro, Chrome, Wi-Fi at 100 Mbps. A read triggered by
  the cover takes 2 to 3 s to show.
- A move made by an ordinary hand movement is not picked up at all.
- In one frame the recognizer did not see a king.
- No corpus games are recorded.

What this does to the hypotheses:

| # | Status | Why |
|---|---|---|
| H1 motion gate never opens | **Leading** | A normal hand move never produces a read; a cover always does. The cover is the only difference in stage A. |
| H2 change gate drops the frame | Open | After the cover, the uncovered frame is compared with the same accepted reference as a normal move would be, so if the cover path passes stage C with the same two changed squares, a normal move should too. Unless the covered frame itself was read and became the reference. The log decides. |
| H3 decode waits for the period to end | Refuted | Cover-per-ply gives one move per ply immediately. |
| H4 upload or server dominates | Open, bounded | Round trip is 2 to 3 s on fast Wi-Fi; upload is small at that bandwidth, so the server is probably 1.5 to 2 s. Speed work goes there once `serverMs` is logged. |
| H5 single plies pending, two-ply wins | Refuted | Same reason as H3. |

The missing king is a separate finding and a useful one. The decoder can
never remove a king (no candidate tier moves a piece off the board), so the
state was safe, but the raw reading was wrong, which means that frame was
bad: a hand, blur, or an occlusion. A reading-sanity check (both kings seen
with probability at least 0.5 somewhere; expected piece total not above the
tracked board's total) turns such a frame into a "bad frame" that is retaken
after a second instead of counting toward a prompt. The same retake timer
also covers the case where a pending frame would otherwise wait for the next
hand motion that may never register.

On data: nothing has been recorded, and the recording protocol in the
original plan (one photo per ply, by hand) has not happened in four days
because it is a chore. The replacement is to let the app record: with an
opt-in toggle, the server keeps every crop the phone sends, the reading it
returned, the client's event log, the "mark" taps, and the PGN the operator
confirms at the end. That is exactly what the model sees, with timings, and
it becomes the corpus through an import script. The plan is
`docs/superpowers/plans/2026-10-21-field-instrumentation-and-recording.md`.

## 10. Owner's ideas on 2026-10-21 evening, with the planner's assessment

**Idea 1: keep a digital model and reject readings that cannot follow from
the last stable position; never let a reading overwrite the position.**

This is the decoder's architecture already (original plan, "Decoder
scoring"). The reading never becomes the position. The tracked position
changes only when one candidate transition (no change, legal move, undo,
two-ply, or, after a pending frame, an illegal move with prior -6) wins by
`acceptMin` and `marginMin`. No tier can remove a king or add a piece.
Before Task 0 of the plan, the reading was consulted only on the squares a
candidate changes, so a wrong piece type on an unchanged square had no
effect at all; that is also the hole described in section 11. After Task 0
(builder commit 0613ede), up to `residualMax = 4` such squares are tolerated
and more than 4 make the frame pending. Task 7's residual column shows
whether 4 is too strict in the field.

Where the owner's idea adds something real:

- The raw reading is still shown somewhere in the UI (the heatmap or an
  overlay), and that is what showed a missing king. The tracked board and
  the raw reading should be visibly different layers: the board is truth,
  the reading is a diagnostic. If the owner ever saw the *tracked* board lose
  a king, that is a real bug and must be reported with the log.
- Readings that are impossible as a whole (no king, pieces appearing) are
  now a frame-quality signal with a retake (Tasks 2 and 3 of the new plan),
  which is the owner's "guard" made concrete.
- The one deliberate hole is the illegal tier. It exists because club
  players do make illegal moves. Its safety comes from the prior, the margin,
  and from being offered only after a pending frame. Whether that is enough
  is a corpus question (gate G2: silent errors 0).

**Idea 2: castling direction was confused after the owner "moved
orientation" before castling.**

Not yet understood. A 180-degree rotation cannot swap castling sides (the
decoder re-indexes the reading under each rotation, and kingside stays
kingside). Three explanations fit, and the log plus one answer from the
owner separate them:

1. Castling was played king first, rook second, and a frame was read in
   between. That frame shows only e1 and g1 changed, which no legal
   candidate explains, so it is pending; if a second such frame arrives
   before the rook moves, the illegal tier can accept Ke1-g1 as an illegal
   king move and the real castling then has no legal explanation. Guard, if
   confirmed: when the changed squares are a strict subset of a legal
   castling's squares, stay pending and retake rather than offering the
   illegal tier. This is a decoder rule and goes through the benchmark.
2. The phone itself was turned or moved, so the corner homography and the
   crop no longer matched the board. The capture should have emitted
   `bumped`; if it did not, the shift detector threshold is the fault.
3. Recognition noise on the rook squares at the board edge nearest or
   farthest from the camera, which is the hardest region at 45 degrees.

Resolved (owner, same night): the castling confusion happened while the
phone was being moved. It is the same failure as section 11, a shifted
scene explained by a lucky legal move, and needs no separate investigation.
Task 0's residual gate and Task 1's pause cover it; the camera-move test in
Task 7 Step 0 is where it is confirmed fixed.

**Idea 3: detect the arm coming in and going out, and use it to time the
read.**

Feasible, cheap, and it is the right shape for the fix to H1. The current
trigger is a whole-frame mean difference, which an arm on the far side
barely moves. Replace it with region motion: per-square energy against the
previous frame on the board plus a border band around it. "Arm in" is a
sustained motion region touching the band; "arm out" is that region gone
with the board still. The read fires on arm out plus the existing settle,
so a piece being adjusted after the hand leaves still waits. No hand or
pose model is needed; frame differencing on the 128 x 128 crop does it.

What anticipation buys: not much on the read itself, since the frame cannot
be taken before the arm leaves. It does buy a warm server connection, the
twin's pre-rendered masks for the legal replies, and a higher sampling rate
for the detector during the move. One cheap extra: the side the arm comes
from. Players sit left and right, so the arm of the player to move comes
from a known side. An arm from the other side is an adjustment, a capture
being cleared, or a takeback, and can lower the legal-move prior for that
frame. This is an idea for the next plan, after Task 5's table shows what
`meanDiff` and per-square energy do during a real hand move.

## 11. Camera movement produced silent moves (owner, 2026-10-21 night)

The missing king was not a recognition miss. The owner was moving the phone
and the app accepted a sequence of moves on its own, one of which took a
king or a queen off the board. This is the one failure the gate metric
forbids (silently wrong plies = 0) and it outranks everything in this brief.

**Why the design allows it.** The decoder's step order, as specified in the
original plan: pick the best candidate `b`; if `b.score < acceptMin`, check
how many squares of the reading disagree with the tracked board and go
pending 'unexplained' when there are more than `disagreeMax`; otherwise, if
the margin is wide enough, accept. The disagreement check runs only on the
low-score branch.

*Correction from the builder, 2026-10-22 (their commit 0461ff8, docs only):*
the live code was looser still. `Decoder.step` had no disagreement check on
any branch; the low-score branch only tested raw evidence against
`unexplainedMin`, and `disagreeMax` was used by the start check alone. So
the paragraph above describes the plan, not the code, and the hole was
wider than written here. The fix below is unchanged by this: it adds the
check on every branch.

A reading of a shifted, rotated or re-cropped board
disagrees with the tracked position on most squares, but a legal move that
happens to match two of those wrong squares scores about +13 (two squares
at `log(0.9 / 0.001)`), far above `acceptMin = 2.0`, and the runner-up is
often far behind. The decoder scores only the squares a candidate changes
and never asks whether the rest of the board still agrees. A sequence of
such frames walks the position anywhere. The king cannot be removed by any
tier, but the queen can be captured, and the king can be moved.

**Why the safeguards did not catch it.**

- The bump detector is a phase-correlation shift on a 64x64 crop with a
  4 px threshold. Picking the phone up is rotation and scale, not a pure
  shift, so the correlation confidence drops and nothing fires. Even when it
  fires, the plan only says it opens a re-frame prompt; it does not say the
  queue stops decoding.
- The stability detector does its job: while the phone moves nothing
  settles, and once it is still the next frame is read. That frame is a
  different scene, and the decoder has no notion of "different scene".

**The fix, in order of importance.**

1. **Residual gate in the decoder.** After choosing the best candidate,
   count the squares where the reading disagrees with the *candidate's*
   board (not the tracked one). If more than `residualMax` disagree, the
   frame is pending 'unexplained' whatever its score and margin. This closes
   the hole for every cause: camera moves, a hand over half the board, a
   wrong crop. It is a synthetic unit test, needs no corpus, and only makes
   acceptance stricter. `residualMax` starts at 4 and is tuned on the
   corpus; the per-frame residual goes into the debug log.
2. **Camera movement pauses decoding until a resync.** Three signals say the
   camera moved: the existing `bumped`, the phone's own motion sensors
   (`devicemotion` is available in Chrome on Android without a prompt), and
   two consecutive frames whose residual against the tracked board exceeds
   a scene-change count. On any of them the queue drops frames and shows
   "Camera moved". It resumes only after the sensors are quiet and one
   settled frame agrees with the tracked position under the best of the
   four rotations. If it does not agree, the re-frame prompt opens and
   nothing is decoded until it does.
3. **Recovery.** An always-visible "Undo last move" so the operator can
   repair the game in a few taps when something does get through.

These are Tasks 0 and 1 of the plan now; the instrumentation moved behind
them. The builder must confirm the live step order in `decoder.ts` before
Task 0 and quote it in `eval/RESULTS.md`; if the live code already gates on
disagreement before accepting, the mechanism is different and the log from
the next camera-move test decides.

## 12. Builder's report, 2026-10-22, and what `eval/RESULTS.md` adds

- **Task 0 is done** (commit 0613ede): the residual against the candidate's
  board is counted on every branch and more than 4 disagreeing squares make
  the frame pending 'unexplained' whatever the score and margin. Task 1
  (pause and resync) is next; the Undo button is in it.
- **Two corrections to this brief**, both applied above: section 11 now
  says the live code had no disagreement check at all, and section 10 no
  longer claims an unchanged square can never matter.

Facts from the owner's copy of `eval/RESULTS.md` (entries to 2026-10-20)
that bear on response speed and on what to expect:

| Fact | Where | Consequence |
|---|---|---|
| Model input is 644 x 644 RGB; normalisation is inside the graph | Task 4 export | The phone can crop to the board plus margin and resize to 644 before upload. A 644 px JPEG at quality 85 is roughly 80 to 150 KB, so upload stops mattering on any network. |
| Native ORT CPU, 2 threads, on the 2 vCPU Lighthouse VM: 1.3 to 1.6 s per photo; PyTorch 1.0 to 1.15 s | Tasks 2, 4, board-detection Task 0 | The server read is near its floor on this box. The 2 to 3 s the owner sees is settle 0.4 s plus about 1.3 s of model plus overheads. Under 2 s needs a faster box or skipping the recognizer when the twin's silhouette term alone is confident (already in the design). |
| Dynamic int8 fails parity (max prob diff 0.56 to 0.77) and is not faster | Task 4 | Quantisation is not a speed lever here. Do not spend time on it. |
| The browser WASM path takes 5.3 s per read on the server CPU | Task 4 | Confirms server-by-default. |
| Board-detection plan Tasks 0 to 7 are built: centroids (decoder layer 2 and 3, head 4 carry the geometry), grid fit, tap-free start with nudge handles, camera pose, twin, scorer terms, bench modes, dataset adapter | 2026-10-19 and 10-20 entries | Every gate G4, G5, G6 is NOT DECIDED for one reason only: no corpus. Session recording (plan Task 5) is therefore the critical path for the whole project, not just for the trigger thresholds. |
| The headless `bump` test shows the app saying "The camera moved", holding the position, and resuming after re-tapping the corners | Task 14 e2e | A pause path already exists for `bumped`. Task 1 should extend it to the sensor and scene causes and add the agreement check before resuming, not build a second one. |
| The dev VM currently answers as the LIVE API on port 8100 | board-detection Task 2 e2e | Production is still on the dev VM. The new Lighthouse box from the design spec has not happened; recording data will land on this VM's disk. |

What this means for the owner's speed goal: the trigger failure (a move not
picked up until the lens is covered) is the real latency problem and is
worth minutes per game; the model read is worth at most a second and is
near the floor of the current hardware. Fix the trigger first, measure,
then decide whether a faster box is worth its cost.
