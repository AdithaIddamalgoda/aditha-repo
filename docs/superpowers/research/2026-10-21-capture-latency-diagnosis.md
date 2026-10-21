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
