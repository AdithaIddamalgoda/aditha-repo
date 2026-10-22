# Review: recording protocol v2 and the persistent-board design (builder commit d7cc6f8)

Written 2026-10-22 by the planner. Neither document is built. The review is
against the two texts as pasted by the owner; the builder's repo files
(`docs/recording-protocol-v2.md`, `docs/persistent-board-design.md`) are the
source of truth for wording.

## Verdicts

- **Recording protocol v2: approve with six changes.** The one idea, "every
  frame taken while no piece is moving is labelled for free by the script",
  is exactly right and it produces the hand-versus-clean energy data the
  trigger plan needs. The scripted 29-ply game is legal (checked by the
  builder with python-chess; the special moves fall where the text says).
- **Persistent-board design: approve the principles; three things must
  change before it becomes a plan**, and one document it depends on has
  never reached the planner.

## A. Protocol v2: required changes

1. **Captured pieces: record both ways, do not legislate the tray.** The
   owner is right that a club player puts captured pieces beside the board,
   inside the crop margin, and the product must survive that. The tray
   outside the picture is a controlled baseline, not the rule. S1 uses the
   tray; S2 puts every captured piece beside the board where a player would,
   on the side of the player who captured it. Because the script fixes the
   ledger exactly, every frame with pieces in the margin is labelled: this
   is the data for section C below. Games 38 and 39 showed the failure; the
   protocol should reproduce it on purpose, not avoid it.
2. **Mark taps will trip the motion sensor.** Task 1 pauses decoding when
   the phone's acceleration exceeds 1.5 m/s squared. A finger tap on a
   clamped phone is a short spike well above that; game 39 already saw 2 of
   67 taps coincide with "Camera moved" before the sensor exists. Fix in
   Task 1, not in the protocol: the motion classifier needs sustained
   motion (above threshold for at least 300 ms, three consecutive samples)
   and ignores the 500 ms after any touch event on the page. The protocol
   keeps "tap gently with the free hand".
3. **Add a deliberate intermediate castling frame.** Ply 11 (O-O): king to
   g1, hand out, hold 3 s, hand in, rook to f1. Ply 14 (O-O-O): the same
   with the rook first. Game 39 committed a rook move and a king move as two
   plies; the fix (strict acceptance in section B) must be tested against a
   frame where only half the castling has happened and the hand is away.
4. **Add two disturbances to block 1:** a piece slid along the board rather
   than lifted (a slide produces a smear of change across several squares),
   and a piece knocked over and stood up again on its square. Both were in
   the original corpus protocol and both happen at a club.
5. **The 3 s still after each move is the measurement of the trigger, say
   so.** The owner should note any ply where the move list did not update
   within those 3 s. That single column, from S1 to S3, is the latency gate
   for the trigger plan.
6. **S0 angle sweep: hold 10 s per view, not 8**, so the relocation has
   time to settle, read, match and show its result before the next move.
   Write down what the screen said at each view (resumed, rewind offer,
   mismatch, nothing).

Everything else stands: one Mark per ply after the hand leaves, End session
with the true PGN pasted, the one-person two-arm routine, light changes
noted per block, 90 minutes with S1 first if short of time.

## B. Persistent-board design: what must change

**B1. Legal-only history: yes, with a one-tap exception.** Agreed that
nothing outside the legal-move graph is ever committed automatically. But a
casual game does contain illegal moves, and the operator should not have to
rebuild the board by hand to continue. When a single illegal move of one
piece explains two consecutive clean frames exactly (residual 0), the fix
sheet offers it as the first option, "Accept illegal move Ke1-e3?", and the
tap writes the discontinuity. That keeps the history legal by construction
and the operator's cost to one tap.

**B2. One belief, not a belief and a beam.** The board-detection plan's
Task 5 gives the decoder a beam of three hypotheses; this design adds a
belief with a checkpoint root and weighted legal tails. They are the same
thing. The belief's tails *are* the beam; the design should say the beam
is replaced, name the file (`belief.ts`), and move the twin terms to score
tails. Two parallel hypothesis stores will disagree in the field.

**B3. The trigger's expected-change masks come from the belief.** Section 4
of the state-aware note precomputes the squares that can change next from
the committed state. With a belief, they come from the union of the tails'
next legal moves. This is where the owner's "digital board, grid and
recognition in tandem" lives; the design should own it rather than leave it
to the trigger plan (see section C).

Smaller points, agreed as written: game and view separated; snapshot after
every commit; resume is untrusted until relocation agrees; recollection by
placement under the four rotations with checkpoints searched only after the
committed state and its continuations; checkpoint after two clean frames at
least 1 s apart; keyframes out of the first version; "never silent".

Add to the gates: median time from hand leaving the board to the move shown
at most 2.5 s on clean plies (the owner's original ask), and offline replay
of a recorded session must reproduce the live decisions ply for ply
(determinism, so the recordings stay a test set).

## C. The owner's point, made concrete: pieces beside the board

The owner wants the virtual board to reason pieces off the board rather than
banning them from the picture. Three facts decide how:

1. The recognizer returns 64 per-square probabilities, nothing for the
   margin. A piece lying in the margin is not "detected outside the grid";
   it leaks into an edge square's reading. So geometry alone cannot tag it.
2. The grid fit says exactly where the 64 squares are in the crop. The
   change footprint (per-square energy plus a border band) says where
   pixels changed. A piece set down in the margin changes the band and no
   square.
3. The material ledger is exact: start counts minus captured, per type and
   colour. A reading with more of some piece than the ledger allows is
   explained by an off-board piece, and the ledger says which type.

So the tandem is: a change confined to the border band is classified
**off-board** by the trigger and never causes a read; if a later read shows
an excess of a type the ledger says is captured, the edge squares adjacent
to the band change are marked **suspect** and their reading is down-weighted
(the same weight the twin's visibility term uses), so the decoder cannot
move a piece onto them from the reading alone. This handles captured pieces
beside the board and the spare queen for promotion with no rule about trays.
It belongs in the design's section 4.6 (the ledger) and in the trigger
plan's classifier as a fourth class.

What it cannot do: tell a captured piece in the margin from a board piece
that was slid half off its square. Both change the band and an edge square.
That case stays "occluded" until the next clean frame, which is the right
answer.

## D. What the planner has not seen and needs

1. **The owner's technical review**, `.claude/2026-10-19-chess-rechnical-review.md`,
   sections 17 to 36, which this design is built on. Please commit it under
   `docs/` or paste it. I cannot review a design against a document I have
   not read.
2. **`eval/RESULTS.md` as of today**: field sessions 2 to 4 (games 38 and
   39), the "three deadlock modes", and the 2026-10-22 shift experiment.
3. **The hand-versus-clean energy distributions** from game 36 asked for on
   2026-10-22. Protocol v2 will produce better ones, but the 94 frames exist
   now.

## E. Recommendations on the design's four decisions

1. Never auto-commit an illegal move: **yes**, with the one-tap offer in B1.
2. On reload: **offer automatically, resume on a tap**, and only through
   relocation. A card "Resume game 36 from move 14?" with the position shown;
   never a silent resume.
3. Pixel keyframes out of the first version: **yes**.
4. A second phone on the same game: **out of scope** until one phone passes
   the gates. The view records may stay as designed; nothing schedules it.

## F. Order from here

1. Builder applies A1 to A6 to the protocol and B1 to B3 to the design;
   sends the three items in D.
2. Owner records S0 to S3 after the clean redeploy, with the sensor debounce
   from A2 in the build, or with Task 1's sensor pause disabled for the
   recording if it is not ready.
3. Planner writes the trigger plan from S0 and the still blocks (P1), then
   turns the design into the P2 to P4 plan with `superpowers:writing-plans`.
