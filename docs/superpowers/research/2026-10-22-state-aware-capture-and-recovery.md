# State-aware capture and recovery: assessment of the first recorded game

Written 2026-10-22 by the planner from the builder's analysis of session
game 36 (94 frames, 1169 s, build 690e8c3-dirty) and the owner's comments.
Companion to `2026-10-21-capture-latency-diagnosis.md` and the plan
`../plans/2026-10-21-field-instrumentation-and-recording.md`.

## 1. Is one badly recorded game usable?

Yes, and it is the most useful thing the project has produced so far. The
sessions hold the exact 644 x 644 crops the model saw, the 64 x 13
probabilities per crop, and per-square energy and timings per event. A game
in which the camera moved, a hand rested over the board, and the position
was lost is a better test set than a clean game, because it contains every
failure the app must survive. The builder's 22-ply replay is a machine
reconstruction and the owner must confirm it before it is used as a label.
Two protocol notes for the next session: press End session so the PGN is
saved, and tap Mark for every ply or not at all (7 marks in the first 72 s,
two matching no change, cannot label anything; the replay will).

## 2. What the builder found, and what each failure says

| Time | Builder's finding | What it tells us |
|---|---|---|
| 61.8 s | A hand-occluded frame accepted as Nf3-g1 with score 12.2 and residual 2 | The residual gate (limit 4) does not catch a frame where a hand changes the reading confidently on just two squares. Hands must be kept out of the decoder *before* the read, by their footprint in the energy map, which the model's probabilities do not show. |
| 156 s | Same false Ng1 at the acceptance limit (score 4.9, residual 4), committed | Residual exactly at the limit still commits. The limit is a knob; the real fix is the same as above. |
| 164 s | Next frame explained as the two-ply d3d4 g1f3; game illegal from ply 14 | Once the state is wrong, every later frame is explained relative to a wrong state. Recovery needs a trusted earlier position, not a deeper search from the current one. |
| 215 to 220 s | A knight held in the air accepted as g8-d7, then d7-f6; one move became two plies, side to move wrong, every later move "illegal" | Same root as 61.8 s (a transient frame read and accepted) plus the consequence that the move count drives side to move. Checkpoints plus a legal-sequence search fix the consequence; the trigger fixes the cause. |
| From 409.7 s | No more reads; bogus e1e4 at 413 s | Probably the board was lost after a camera move. Phase events are missing from the log, so this is not proven. Logging gap, fixed below. |

Timing: 2 s from settle to accept on a clean frame (near the floor for this
server); 12 to 33 s when hand frames are read first. The whole latency
problem in this session is hand frames, not the model.

## 3. Why reframing from the other side never recovers (the owner's orientation question)

The owner moved the phone from the left of the board to the right. That is
a 180-degree rotation of the board in the image, and the model labels
squares by where they are in the picture (RESULTS, 2026-10-19: "the model
labels squares physically"). So after the move the reading arrives rotated
180 degrees relative to the decoder's current rotation.

The decoder scores every candidate under all four rotations with a prior
toward the current one, and the rotation changes only when an *accepted
move* wins under another rotation. After the residual gate, a rotated
reading looks like this: under the current rotation every candidate
disagrees on most squares, so the best candidate is pending 'unexplained';
under the correct rotation the best explanation is "no change", which
scores 0 and is never "accepted" (it is the fallback when nothing reaches
`acceptMin`). The step therefore returns pending under the old rotation on
every frame, the rotation never switches, and the app is stuck exactly as
the owner saw: reframing does not help, castling later reads as a stray
rook move, and nothing matches.

**Fix (small, goes into Task 1 of the current plan):** whenever the best
candidate is pending 'unexplained' under the current rotation, run `check`
(best of four rotations against the tracked board, already specified for
the resync). If another rotation has residual at most `residualMax`, adopt
it, log a `rotated` event, and treat the frame as no change. The same
check runs on resume after a pause. The owner's symmetry worry is small: a
chess position with one white king is never invariant under a 90 or 180
degree rotation that keeps colours, so the only confusable case is a reading
whose colours are unreliable; that is exactly when the residual gate keeps
the decoder from committing anything.

Camera geometry after a move: the grid and twin pose come from the start
frame's centroids and must be refit after any camera move. The board-
detection plan's `refit` on `bumped` does that; the sensor and scene causes
from Task 1 must call it too.

## 4. The trigger the owner is asking for: read only a move-shaped change

The owner's idea, "use elimination from the digital board to decide which
squares matter and when to capture", is the right trigger and it replaces
the whole-frame motion test that is the leading suspect for the missed
moves.

The tracked state says which squares *can* change next: the from and to
squares of every legal move (plus the rook squares for castling, the
captured pawn for en passant), the squares of a one- or two-ply undo, and
the union of two consecutive legal plies. That is at most a few hundred
small sets of 2 to 4 squares, precomputed as 64-bit masks the moment a
position is committed. Everything else on the board is expected to stay
the same until the next commit.

Per video frame, against the last accepted frame (the reference `markAccepted`
already keeps), after the existing shift alignment and brightness
normalisation: compute the per-square energy, weight it by each square's
projected area so the far ranks count, threshold it at a multiple of the
noise floor measured on quiet frames, and call the changed set `M`.

Classify `M`:

- empty: **quiet**, nothing to do;
- a subset of one of the expected-change masks: **move-shaped**, read as
  soon as the stability detector settles;
- anything else (a hand, a forearm, the player's shadow, a knocked piece,
  the camera moving): **occluded**, do not read.

Transitions do the rest. Occluded growing from the border is the arm
coming in; occluded collapsing to move-shaped is the arm leaving with the
piece placed; move-shaped that holds for `stableMs` is the read. A frame
with a hand resting on the board is never read, so the 61.8 s and 215 s
failures cannot happen, and the 12 to 33 s cases vanish because no bad
frame is in the queue ahead of the good one. If occluded persists longer
than about 8 s, read once anyway (the residual gate protects the state)
and show a hint that something is covering the board. An occluded set that
covers most of the board for two seconds is the scene-change signal Task 1
already defines.

What is needed before the thresholds are set: from the 94 frames, the
per-square energy of frames the builder marks as clean versus frames with
a hand in view, and the energy on the true move's squares versus the rest.
The data exists in `events.jsonl`; the labelling is an hour of the
builder's time with the crops. This is the measurement the brief asked for
in section 4 and the plan's Task 7 Step 3; the builder's table covered the
timings but not these distributions.

## 5. The builder's "anchor search": agree, with conditions

The proposal: keep checkpoints (positions committed on clean, high-
confidence frames); after an illegal commit, an ask, or a clean frame the
tracker cannot explain, search legal sequences of up to three plies from
the last checkpoint, score each on the squares that differ from the
checkpoint, show the best few, and adopt one automatically only on an
exact match. Offline it rebuilt all 22 plies where the live decoder
managed 12.

Assessment: sound, and cheap to build on what exists (`generate` for legal
moves, `scoreAll` for the scoring, the fix sheet for the choice). It is the
right answer to "undo reaches back two plies": a trusted position to search
from instead of the corrupted current one. Conditions:

1. **It is recovery, not prevention.** The trigger in section 4 and the
   rotation fix in section 3 come first; the search cleans up what they
   miss. Built in the other order, the app would recover from failures it
   should not have.
2. **Checkpoint means something strict:** a committed position whose frame
   had residual 0 under its rotation, no square with a maximum probability
   under 0.9, and no pause, retake or ask in the previous frame.
3. **Exact match means strict too:** residual 0 against the candidate
   sequence's final board, and the runner-up sequence at residual 2 or
   more. Anything looser goes to the fix sheet as ranked paths; the
   operator chooses.
4. **Budget:** three plies from a middle game is about 30 cubed sequences.
   The bench measured 2,793 candidates in about 80 ms on the VM, so this
   is one to two seconds on the phone. It runs in the worker, off the read
   path, and only on the three triggers listed, never per frame.
5. **The manual Undo has no depth limit.** The two-ply reach the builder
   mentions is the `undo1` and `undo2` *detection* tiers; the operator's
   button must walk the history to any depth. That is a one-line check in
   Task 1.
6. **Log it.** `anchor` events with the checkpoint ply, the paths
   considered, and whether one was adopted or offered.

## 6. Logging gaps to close now

Added to Task 4 of the current plan: `decode` events carry the chosen move
in UCI and the tier; `answer` events record every action on the fix sheet
(the candidate chosen, "nothing moved", manual drag, undo) so they stop
living only in the API journal; `phase` events for every state of the app
(finding the board, tracking, paused, asking, lost); `rotated` and `anchor`
events as above. The deployed build hash must be clean; `-dirty` in a
field session means the data cannot be tied to a commit.

## 7. Order of work from here

1. Owner confirms the 22-ply replay and says when the phone was moved.
2. Builder: finish Task 1 with the rotation rule and the unlimited Undo;
   close the logging gaps (Task 4); label the 94 frames clean versus hand
   and produce the energy distributions.
3. Planner writes the trigger plan (section 4) from those distributions,
   with the anchor search (section 5) as its second part.
4. Record two more games with End session pressed, one per side of the
   board, before any threshold is declared final.

## 8. Questions for the owner

1. Does the 22-ply reconstruction match the game you played?
2. At roughly what point in that game did you move the phone to the other
   side, and did you re-run the board detection afterwards or re-tap the
   corners?
3. In this build, were ordinary moves picked up without covering the lens?
   The builder's table shows clean moves accepted about 2 s after settle,
   which would mean the trigger failure from your first report is gone or
   intermittent. I need to know which.
