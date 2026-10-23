# Code review: chess_daily at 2c4a834 (branch feat/chess-camera-eval-bar)

Written 2026-10-23 by the planner, from the code, the test files' names and
`eval/RESULTS.md` through the 2026-10-22 entries. The test suite could not
be run in the planner's sandbox (the lockfile resolves packages from a
Tencent mirror the sandbox's proxy refuses, and one package is absent from
the public registry), so every finding is from reading, with the failure
scenario taken from a recorded game where one exists. Lines are from the
files as read; the builder should confirm them before editing.

Scope: the decision path only. `web/src/decoder.ts`, `queue.ts`,
`capture.ts`, `score.ts`, `candidates.ts`, `game.ts`, `sanity.ts`,
`motion.ts`, `homography.ts`, `gridfit.ts`, `startsession.ts`,
`recognizer.ts`, `recording.ts`, `app.ts`, and `server/app/recording.py`.
Not reviewed: the table, accounts, leaderboard, story, admin and sync code.

## Corrections to the planner's earlier notes, from reading the code

- The decoder does adopt a rotation without an accepted move: a "nothing
  changed" explanation that wins under another rotation switches it
  (`decoder.ts` 227 to 232), and `stuck` plus `turnedTo` (296 to 308) now
  handle the pending case. The "stuck rotation" mechanism in the 2026-10-22
  note was a guess that the code does not support as written.
- The move-reading crop is square by construction (`cropRect`, `homography.ts`
  89 to 100); the squash concern applied only to the whole-frame
  board-finding read, and RESULTS shows squash is no worse there.

## Verdict

The architecture is the owner's concept: the recognizer votes on
transitions from a tracked state and never writes the board. Three places
let that invariant leak, and all three show up in the recorded games as the
first wrong commit of a cascade. They are small changes. Below them are the
reference-frame design flaw the builder's own offline test exposed, a
missing rotation of the grid that will bite the moment a session is recorded
from Black's side, and a set of smaller improvements.

## A. Logic flaws, in order of damage

### A1. The illegal tier is offered on every frame (decoder.ts 103, 189)

`TIERS` includes `illegal`, and `judge` generates it on every frame. The
original design offered it only after a pending frame (`pendingCount >= 1`).
With the probability floor at 1e-3, one square read confidently wrong is
worth up to +6.9, so two such squares make +13.8, and an illegal move with
its -6 prior scores +7.8: above `acceptMin` 2.0, and with "nothing changed"
at 0 as the runner-up the margin is also met.

Evidence: game 39 at 134 s, `c6b8` committed as `illegal`, residual 1, score
6.0, margin 5.1, from a hand frame; game 38, three illegal commits at 192 to
199 s from one hand holding a piece; castling committed as `h1f1` then
`e1g1`; a bishop move as `b4b6` then `b6c5`. Every cascade the builder traced
begins this way (RESULTS, sessions 2 to 4, item 1).

Fix now: generate `illegal` only when `this.pendingCount >= 1` (one
condition in `judge`), and then, per the design's B1, never commit it
without the sheet. Test: a reading that shows one piece moved to a square no
legal move reaches, on a fresh frame, is `pending`, not `move`.

### A2. A move is accepted on the sum of its squares, not on each (score.ts 28 to 34; decoder.ts 218)

`scoreCandidate` sums the log-ratio over the changed squares. A piece
lifted off its square gives the from-square +6.8 on its own (the square is
confidently empty); any to-square where the reading is merely unsure of
"empty" (say 0.1 on the piece) costs only about -2.3, so the sum clears
`acceptMin`, and the decoder commits a move to wherever the reading is least
sure. The residual gate does not catch it because the rest of the board
agrees.

Evidence: game 36 at 215 to 220 s, a knight held in the air accepted as
`g8d7`, then `d7f6`; game 36 at 61.8 s, `f3g1` with score 12.2 and residual 2.

Fix now: a per-square floor. Accept a candidate only when every changed
square individually prefers the candidate's class over the tracked one by
at least `perSquareMin` (1.0 in log units, tuned on the corpus); otherwise
the frame is pending 'unexplained'. One loop in `judge` over
`diffSquares(root.board, best.scored.candidate.board)` under the winning
rotation. Test: from-square empty at 0.9, to-square empty at 0.85 and the
piece at 0.1, is pending; both squares at 0.9 for the move is a move.

### A3. The hand gate's release reads the frame as a move candidate (capture.ts 126 to 135, 405 to 413)

`StabilityDetector.hold` releases after `retakeMax` retakes and the frame is
then read "like a change" and can be committed. The builder's offline test
(RESULTS, sessions 2 to 4, item 4) ran exactly this variant on game 36 and
it committed the same false `f3g1`; the variant that read a held frame only
for `Decoder.check` and re-referenced on agreement recovered all 22 plies.
The deployed build (23b7bc4) ships the committing variant. A player who
rests a hand on a piece for three seconds while thinking, which is normal,
triggers it.

Fix now: a released frame is read for `check` only. If `check` passes, the
frame becomes the reference (`markAccepted`) and nothing is committed; if it
fails, the frame is dropped and the scene watch gets the residual. The queue
needs a `checkOnly` flag on the pushed frame, or the app can call the
recognizer and `decoder.check` directly as `resync` does. Test: four
occluded settles in a row never produce a `move` outcome.

### A4. Hand frames become the reference picture (app.ts 174 to 176; queue.ts 127)

`onOutcome` calls `markAccepted` on every `nochange`, including a forced
bad frame the decoder shrugged at and a `preview` frame that was never
judged. A hand frame that the model happened to read through (residual at
most 4, score low) becomes the picture all later frames are measured
against; the next clean frame then differs on 50 or more squares and is
itself classified occluded. RESULTS, game 36, item 6: 16 of 37 decoded hand
frames became the reference; the 9 clean frames measured against them look
exactly like hand frames (tables 2 and 3, row 2).

Fix now: `markAccepted` only for frames whose settle verdict was `change`
with fewer than `occludedSquares` busy squares (carry the count on
`StableFrame`), and never for forced bad frames or preview frames. Combined
with A3, the only other way to a new reference is the check-only path, which
is the rule the builder's test found to work.

### A5. The fitted grid is never turned by the calibrated rotation in the app (app.ts 364 to 374; homography.ts 56; benchlib.ts 180)

The grid fit names its corners as the model names squares ("index 0 is the
model's own a1"). The bench turns them by the decoder's rotation with
`turnCorners` before building the homography; `applyCorners` in the app does
not. So the energy array, the overlay, `orientationFromCorners`, and
everything else indexed by square in the capture is in the model's frame,
while the decoder's board is in the true frame. Game 36 ran at rotation 0, so
nothing showed. The protocol's S2 (Black's side) will run at rotation 2:
the hand gate still works (it only counts squares), but the move-shaped
trigger, the twin's visibility, and the suspect-square rule would all look
at the wrong squares, and the virtual board's orientation would be shown
wrong.

Fix now: after `calibrate` (and in `resume` and on a `rotated` outcome)
rebuild `H` from `turnCorners(corners, decoder.rotation)` and keep the raw
corners separately for the overlay. Test: a start reading rotated 180
degrees yields an energy array whose busiest square after a synthetic e2e4
is e2 or e4, not d7 or d5.

### A6. The energy grid is displaced from the physical board by about a square (RESULTS, game 36, item 1)

The code path is consistent (`grabGray` 435 to 440, `squareEnergy`
107 to 144, `judgeSettled` 396): a crop pixel maps to the image through the
crop origin and scale, then through the inverse homography, correctly. The
displacement is therefore in the fitted corners themselves: the attention
lattice sits about 1.4 ranks and 0.5 files from the squares at this view.
The grid fit has never been measured against labelled corners (G4 part one
is undecided), and on this one game it is off by more than the plan's 0.15
square widths by an order of magnitude.

Fix, in two steps. Diagnose: on the next recorded session, save the overlay
of the fitted grid on the start crop (one image, in the session folder), and
record the fit's `candidate` head, inliers and rms in `session.json`. Then
self-calibrate: every accepted move gives two known squares and two energy
blobs; after six plies, fit a least-squares correction homography from the
blob centroids to the squares' ideal centres and apply it to `H` for the
energy and the twin only (the model does not need it). That removes the
dependence on the attention lattice being exactly on the squares, which the
twin plan assumed and no measurement supports.

### A7. The bump test runs before the occlusion test (capture.ts 161 to 167)

`judgeSettled` computes `globalShift` first and returns `bumped` on
confidence above 0.5 with a shift over 4 px, then counts busy squares. A
forearm across the board is strong structure; normalised cross-correlation
can lock onto it with a confident spurious shift, and the app then abandons
the game to look for the board (`cameraMoved('bumped')` goes to
`findBoard`). Not seen in the logs read so far, but the e2e bump test uses a
clean shift and would not catch it.

Fix: count busy squares first; when the frame is occluded, do not evaluate
the shift. A bump with a hand in view is caught on the next clean frame.

### A8. The retake loop can read a resting hand up to three more times after a release (capture.ts 126 to 135, 102 to 113)

After `hold` releases it resets `retakes` to 0, so a pending outcome on the
released read arms another retake, and so on: up to three more reads of the
same hand frame, 1.3 s each, each a chance to commit. A3 removes the commit
risk; the cost remains. Fix: a released frame consumes the still period's
retake budget; a new budget only after the next `moving`.

## B. Smaller logic points

- **Extra crops are read lazily, then averaged with the first (queue.ts 148
  to 158).** The restore of `pendingCount`, `beam` and `rotation` before the
  second step is correct, but the mean of a clean first crop and an occluded
  third crop (100 ms apart; a hand entering) can pass sanity and the residual
  gate with evidence from neither. Average only crops whose sanity passes
  individually, or drop the averaging: RESULTS shows frames of one position
  share their errors, which is what the decoder comment on `step` says too.
- **`resync` reads without a `seq` (app.ts 513)** so the server files that
  crop under no frame number. Pass `{ seq: f.seq }`; the importer then sees
  the resync frame.
- **`disagreeing` counts a square only when the reading's best class has
  probability at least 0.2 (score.ts 40 to 48).** A hand that turns squares
  into diffuse readings (nothing above 0.2) is invisible to the residual gate
  by design. That is right for the gate, but it means the residual cannot
  detect occlusion; the energy count must, which is why A3 and A4 matter.
- **`SceneWatch` is fed the residual of every outcome including `move`
  (app.ts 669).** A move's residual is against the new board, so this is
  fine, but a `badframe` is skipped while a forced one's decoder outcome is
  not; harmless, noted for the log reader.
- **Side to move after an illegal move comes from the ply count
  (candidates.ts 248).** Known; the design's legal-only history removes it.
  Until then one split move (game 36, 215 s) flips every later candidate
  set, which is what made "every later move illegal".
- **`pick` resolves promotion ties to the queen within 0.1 (decoder.ts 277
  to 286)** and removes the ties from the rivals; correct and well
  commented.
- **The motion classifier** (motion.ts 264 to 280) is right, including the
  touch guard. One gap: `sustainSamples` 3 at 60 Hz is 50 ms, so the 300 ms
  `sustainMs` is the binding rule; fine, but say so in the constant's
  comment so nobody lowers it.
- **`checkReading` compares log probabilities in Float32** and documents
  why (sanity.ts 214); good. `too-many-pieces` fires on pieces beside the
  board inside the crop (26 bad frames in game 39): the ledger rule in the
  design will replace it, and until then the margin should be masked in the
  crop (section C).

## C. Experiments the builder can run on existing data, no deploy

1. **Mask the margin.** Paint everything outside the board quad plus 0.4
   square of margin in neutral grey on the recorded crops of games 38 and
   39, re-read them through the server, and count: residual against the
   anchor positions, `too-many-pieces` flags, and `Decoder.check` refusals
   in the check-only replay. If the four refusals in game 39 disappear, the
   client masks before upload; it is six lines in `grabCrop`.
2. **Per-square floor replay.** Re-run the offline harness with A1 and A2
   applied, K at 12, and the check-only re-reference: the target is 0
   illegal-tier commits and 0 silent wrong plies on all three games, and the
   plies recovered compared with the 22, 14 and 84-anchor baselines.
3. **Grid offset per session.** Fit the constant offset of energy against
   true move squares for games 37 to 39 as was done for 36. If it differs
   per view, A6's self-calibration is confirmed as the fix; if it is the
   same, something upstream is systematic and worth one more look at the
   centroid export.

## D. Code quality

- One homography implementation (`homography.ts`), reused by the grid fit,
  the twin and the bench: good.
- Configuration is in one object per module (`DEFAULT_CONFIG`,
  `DEFAULT_CAPTURE`, `DEFAULT_SANITY`, `DEFAULT_MOTION`), and the capture
  comments cite RESULTS for the hand-gate numbers: good. `SCENE_CHANGE_RESIDUAL`
  and the `need = 2` in `SceneWatch` are the exceptions; move them into a
  config object with a RESULTS citation when the trigger plan sets them.
- Tests are named after behaviour and the recorded readings exist; the
  decoder tests should now include replays of the three recorded games'
  readings as fixtures (the anchor positions are the labels), so A1 to A4
  are pinned by real frames, not only synthetic ones.
- `app.ts` at 967 lines holds the session state machine, the recording
  client, the fix sheet wiring and the diagnostics. The state machine
  (`phase`, `cameraMoved`, `resync`, `resume`, `onOutcome`) is the part that
  must be right and is the hardest to test through the DOM; lifting it into
  a pure `session.ts`-style module with the DOM calls injected would let the
  pause and resync paths be unit-tested the way the decoder is.
- `web/package-lock.json` resolves packages from `mirrors.tencentyun.com`.
  Anyone building outside that network, including the planner's sandbox,
  cannot install. Regenerate the lockfile against the public registry, or
  document the mirror as a requirement.

## E. What to do in which order

1. A1, A2, A3, A4 with their tests, one commit each, then the replay in C2.
   These close the first wrong commit of every recorded cascade.
2. A5 before the owner records S2.
3. C1 and C3 on the existing recordings.
4. A6's diagnostic on the next session, then the self-calibration as part of
   the trigger plan (roadmap stage 4), where the move-shaped classifier
   needs a grid that is on the board.
5. Everything in the design (legal-only history, checkpoints, belief,
   persistence, recollection) as the roadmap says; nothing here changes
   that order, and A1 to A4 make it start from a decoder that no longer
   corrupts the state it will checkpoint.
