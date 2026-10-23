# The virtual board as source of truth: bridging missed frames and camera moves

Written 2026-10-23 by the planner for the owner. Answers: how far a
legal-sequence search should reach, what rule decides when the board and
the recognizer disagree, whether a separate logic engine is needed, and
what the code review will look for once the repository is reachable.

## 1. The idea, stated as an invariant

The owner's concept, in one line: **the recognizer never tells the app
what the position is; it only votes on which legal transition, if any,
turned the last trusted position into the one in the picture.**

That invariant is already the architecture on paper (decoder design,
persistent-board design, the Task 0 residual gate). What the four recorded
games show is that it was not yet enforced at three points: transient
frames reached the decoder, a lucky legal move could explain a shifted
scene, and a wrong commit had nothing trusted to fall back to. The rest of
this note is how to enforce it fully.

## 2. The conflict rule: board says occupied, model says empty

When a square's reading disagrees with the tracked board, there are only
four explanations, and the app can tell them apart without trusting the
model more:

| Explanation | Evidence that distinguishes it | What the app does |
|---|---|---|
| A legal transition changed that square | the *other* squares of some legal move or two-ply also changed, and nothing else did | score the transition; commit on a strict margin |
| The square is occluded or in shadow | per-square energy against the reference shows a hand or body footprint; the twin's visibility for that square is low | the frame is occluded: no read, retake later |
| The camera or board moved | many squares disagree; the shift detector, the motion sensor or the residual says scene change | pause, refit the grid, resync under the four rotations |
| The model is wrong on that square | the square is one of a few disagreeing, no legal transition explains it, the energy map shows no change there | tolerate it: the residual gate allows a handful; the square never changes the position |

The rule that falls out: **a square's reading can change the tracked
board only as part of a legal transition that the whole frame supports.**
A square reading alone, however confident, is never evidence. That is the
owner's "outrank the recognizer", made operational.

Two refinements, both cheap, both data-driven:

- **Per-square reliability.** Over recorded sessions, count how often each
  square's reading disagreed with the known position on clean frames. Far
  ranks and dark squares at this camera angle will score worse. Use the
  rate as a per-square weight on the recognizer's vote, like the twin's
  visibility weight. It costs nothing at run time and comes straight from
  the protocol v2 still blocks.
- **Material ledger as a hard filter.** Pieces only leave the board. Any
  reading showing more of a type than start-minus-captured is explained
  by a piece beside the board, never by a piece appearing.

## 3. Bridging a missed frame: how deep

The owner's case: the phone was moved after White's move; Black moved
while it was being moved; the next frame showed two plies of change. The
question is how many missed plies the app should bridge on its own.

**Compute is not the limit.** Branching is about 30 legal moves in a
middle game, so depth `d` means roughly `30^d` sequences, each scored on
at most `2d` squares:

| depth | sequences | scoring on the phone | what it covers |
|---|---|---|---|
| 1 | 30 | under 1 ms | a normal ply |
| 2 | 900 | a few ms | one missed ply (the owner's case); already the `twoply` tier |
| 3 | 27,000 | 50 to 200 ms | two missed plies; a camera move that spans a whole move pair |
| 4 | 800,000 | 2 to 5 s | three missed plies; too slow per frame, and see below |

**Identifiability is the limit.** One frame shows only the *net* change of
the whole sequence, and the longer the sequence the more sequences share
a net change:

- At depth 2 the order is forced (White then Black), so a net change maps
  to at most a few sequences, usually one.
- At depth 3 two moves by the same side can transpose (Nf3 then Nc3, or
  Nc3 then Nf3, around a Black reply) and the board cannot tell them
  apart. The position is still right; only the move order in the PGN is
  ambiguous. A piece that moves and moves back, or a capture followed by a
  recapture on the same square, can leave two squares changed where four
  plies happened.
- At depth 4 and beyond the ambiguity grows faster than the evidence, and
  the prior (fewer plies is likelier) starts deciding instead of the
  picture. That is guessing.

**Recommendation.**

- **Online, every frame: depth 2** (the existing `twoply` tier), with its
  prior of -3 so one ply is preferred when both fit.
- **Recovery, on demand: depth 3** from the last *checkpoint*, not from the
  current state. Triggered only when a frame nothing legal explains, after
  an ask, or after the camera-move resync finds the board ahead of the
  committed state. Adopt automatically only on an exact and unique match
  (residual 0, runner-up at least 2 squares worse); otherwise show the
  ranked sequences in the fix sheet. When two sequences give the same
  board, commit the board and mark the move order as "unverified" in the
  PGN comment rather than pick one.
- **Beyond 3 plies: ask.** "The board is 4 or more moves ahead of the
  record; enter the missed moves or set the position." The operator can do
  in ten seconds what no search can do reliably.
- **Prevent the gap where possible.** When the sensor says the camera is
  moving, the screen should say "camera moving, hold the moves". A club
  operator will comply; a gap avoided costs nothing.

This matches the builder's anchor search and the conditions in the
state-aware note, section 5. The depth question is settled: 2 online, 3
in recovery, operator beyond that.

## 4. "If the move looks illegal after a camera move, the frame was bad"

Correct, and the app should encode it as a *sequence* of cheap checks
before it even considers an illegal explanation:

1. Did the sensor or the shift detector fire? Then it is a camera move:
   pause, refit, resync under the four rotations. Never decode the frame.
2. Does the frame's residual against the tracked board exceed the scene
   limit? Same as 1, without the sensor.
3. Is the changed set occluded-shaped (hand footprint)? Retake in a second.
4. Does a depth-2 legal sequence explain it? Commit on margin.
5. Does a depth-3 sequence from the last checkpoint explain it exactly?
   Commit and log.
6. Otherwise: mismatch. Show the disagreeing squares and the ranked
   paths; offer "accept illegal move" only when a single one-piece illegal
   move explains two consecutive clean frames exactly.

The illegal tier is the last resort and needs a tap, as the design now
says. "Look for another frame" is step 3, and it is automatic.

## 5. A separate logic engine: yes, and it mostly exists

The right shape is one pure module with no camera and no DOM, which takes
the trusted state, the candidate readings under the four rotations, the
energy footprint and the ledger, and returns ranked hypotheses with
residuals. The design calls it `belief.ts`; the decoder's candidate
generation and scoring already provide two thirds of it. What is new is
the checkpoint root, the depth-3 search, the strict commit rule, and the
rewind. A "graph" is the wrong mental picture only in one respect: the
state space is a tree of legal sequences from the checkpoint, pruned by
the picture, and it is rebuilt from scratch on each trigger. No learned
network is needed; the rules of chess are the model.

What makes it testable: every recorded session can be replayed through
it offline, ply for ply, against the script's known positions. That
replay harness exists. Gates: silent wrong plies 0, prompts at most 5%,
every history legal, and on protocol v2's camera-move blocks: resume
without a tap at least 9 times in 10, never into a wrong position.

## 6. What the code review will look for (once the repository is attached)

Logic, in order of risk:

1. **Every path by which a square's reading can change the position.**
   There must be exactly one: an accepted transition. Any other (the
   start check writing the board, a resync overwriting it, a manual drag
   bypassing the history) is a flaw.
2. **What `markAccepted` and the reference frame do on pending, retake,
   occluded and paused outcomes.** The reference must advance only on a
   commit or an explicit resync, or the energy footprint lies.
3. **Rotation adoption.** Where and when `rotation` changes; whether a
   "no change under another rotation" result can switch it without a
   residual check; whether the resync sets it.
4. **The averaging of up to three readings per settle.** Whether the mean
   of a clean and an occluded reading can pass the residual gate, and
   whether frames are averaged across a `moving` event.
5. **Side to move and history.** Whether side to move is ever derived from
   a count that can be wrong, and whether `history` can hold a ply the
   rules reject.
6. **The retake and hand-gate release.** No state in which the capture
   waits for a motion event that cannot come.
7. **The pause state machine.** Whether a read already in flight when the
   pause begins can still reach the decoder.
8. **Session recording.** That the crop saved is byte-identical to the one
   sent, that the seq in the log matches the file, and that the squash to
   644 x 644 is the same code path for the saved crop and the read.

Code quality, in order of value: duplicated geometry (one homography
implementation), config scattered across modules instead of one
`DEFAULT_CONFIG`, tests that assert on synthetic readings only where a
recorded reading exists, and any threshold not traceable to a line in
`eval/RESULTS.md`.
