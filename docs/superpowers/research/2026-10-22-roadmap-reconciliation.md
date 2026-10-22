# One roadmap: reconciling the technical review, the persistent-board design, and the current plan

Written 2026-10-22 by the planner after reading the owner's technical
review of 2026-10-19 (`docs/2026-10-19-chess-technical-review.md` in the
builder's repo, 47 sections, tasks R0 to R9) for the first time, alongside
the builder's persistent-board design (P1 to P5) and the current plan
(Tasks 0 to 7). The builder now holds three ordered lists. This note merges
them into one and says which parts of the review the field evidence has
overtaken.

## 1. What the review gets right, and stays binding

- **The virtual chess state is authoritative; camera geometry is
  disposable and recoverable** (sections 2, 47). Every document since
  agrees. The design's game/view split is this principle made into data.
- **The state validity matrix** (18): what survives a phone move, a board
  move, both, a new set. Keep it verbatim in the design.
- **State-validated geometry** (26, 27, R5): a recovered grid is accepted
  only if the known board projects onto what the image shows. This is the
  design's section 6 and the `check` call already built in Task 0.
- **The efficiency correction** (6): the ViT cost is the global encoder,
  so running fewer square queries saves nothing. Correct, and it rules out
  one tempting optimisation for good.
- **Never trade silent correctness for latency** (43). The gate metric
  silently wrong plies = 0 outranks everything.
- **Keyframes start as a rectified template or not at all** (29). The
  design keeps them out of the first version; the review permits that.
- **Gates G7 (one-frame recovery, 9 of 10) and G8 (both moved, zero
  silent errors)** become the recollection gates for P4.

## 2. What the field evidence since 2026-10-19 changes

The review was written before any recorded game. Four games later, the
failures were not where it expected them.

| Review assumption | What the games showed | Consequence |
|---|---|---|
| The main risk is losing the board geometry after a wobble or bump (Tiers 1 to 3) | Every lost game started with a *transient frame accepted as a move*: a hand over the board (game 36, 61.8 s and 215 s), a rook-then-king castling split (game 39), pieces in the margin (38, 39). Geometry loss came last (game 36, 409 s) and only after the state was already wrong. | The trigger (read only move-shaped changes) and strict legal-only commits come before any recovery tier. The review's R-order would build the recovery cascade first and tune later; that order is now wrong. |
| "KEEP the illegal tier; do not remove" (4.3) | The illegal tier, chosen automatically, was the first wrong commit in every cascade; none of the four games ended with a legal history. | Superseded. The tier stays for *generation* so the fix sheet can offer "Accept illegal move?", and nothing illegal is committed without a tap (design B1). |
| Tier 2 needs plane tracking with board features (21, R2) | The recognizer finds the board anywhere in the frame: a shift of the whole picture by one square changed one square (RESULTS 2026-10-22). Re-running the grid fit on fresh centroids after a stable frame covers moderate drift and large jumps in the same step. | R2's feature tracker is not needed. Tier 2 and Tier 3 collapse into "stable frame, refit the grid from centroids, validate against the known state". R1 (`globalShift`) stays as the cheap first step. |
| The heavy-recognizer fast path needs a new small occupancy CNN (10, 32, R6) | The latency problem measured in game 36 is hand frames in the queue (12 to 33 s), not the model (1.3 s on the server). A fast path that skips the recognizer already exists in the design: the twin's silhouette term, which needs no new model or training data, gated by G5. | R6 is deferred until G5 is decided on the protocol v2 recordings. If the silhouette term passes, R6 is unnecessary; if it fails, R6 is the next candidate and G9 is its gate. Do not train a model before then. |
| A separate recovery corpus (35, R8, R9) | Protocol v2 records the same scenarios (S0 and still block 4 are F and G; block 1 is I; block 3 is C and H; S2 against S1 is E) inside ordinary sessions, labelled by the script. | One corpus, one importer, one bench. `recoverbench` becomes modes of `bench.ts` over recorded sessions, not a second harness. |
| The persistent object is one `BoardSession` holding game and geometry (17, R0) | A camera move with the game inside the same object is what tangled them in game 39. | The design's `GameRecord` plus `ViewRecord` replaces `BoardSession`. R0's tests (round trip, no frames persisted, the validity matrix) carry over to `gamerecord.ts` and `views.ts`. |

Nothing above contradicts the review's purpose. It changes the order and
removes two components the review itself marked as "start simple" or
"measure first".

## 3. The single roadmap

Each line names the owning document so nothing is written twice. Gates
are the existing ones; no new gate is invented here.

| Stage | Work | Source | Gate |
|---|---|---|---|
| Done | Residual gate in the decoder; tap debounce in the motion classifier | plan Task 0; review A2 | tests green (715) |
| 1 | Camera-move pause and resync, rotation rule, unlimited Undo; sanity check and retake; debug log, HUD, server timing; session recording; importer | plan Tasks 1 to 6 | the camera-move test in Task 7 Step 0: no move during a phone move |
| 2 | **Interim hand gate** (section 4 below): a settled frame with 8 or more squares over 0.06 energy is occluded, not read | this note | 0 clean frames blocked on game 36 |
| 3 | Owner records S0 to S3 under protocol v2 after a clean redeploy | protocol v2 | sessions imported, PGN saved |
| 4 | **P1 trigger plan**: move-shaped, occluded, off-board and quiet classes from the belief's expected-change masks; arm in and out; read on move-shaped plus settle | state-aware note section 4; review section C of the protocol review | median hand-off to move shown at most 2.5 s on clean plies; no hand frame read in blocks 1 and 2 |
| 5 | **P2 legal-only commits, checkpoints, belief, anchor search, one-tap illegal** | design sections 4 and 8; review R0 tests | silent wrong plies 0; prompts at most 5%; every recorded history legal |
| 6 | **P3 persistence and verified resume** | design section 5 | reload resumes through relocation only |
| 7 | **P4 recollection across camera moves**: stable frame, grid refit from centroids, `check` against committed state, continuations, checkpoints; `ViewRecord` per pose; `globalShift` as Tier 1 | design section 6; review 22, 26, R1, R4, R5 | G7 9 of 10, G8 zero silent errors, time to resume at most 5 s |
| 8 | **Twin terms benchmarked** on the recordings | board-detection plan Task 6 | G5 |
| 9 | Only if G5 fails: R6 occupancy fast path | review 32 to 34 | G9 |
| 10 | Fine-tune on the recorded sessions | board-detection plan Task 7 | G6 |

Twin and fine-tune tasks run in parallel on the VM from stage 3 on, as the
review says; they must not block stages 4 to 7.

## 4. Interim hand gate from the measured energies

The builder's tables on game 36 (91 crops): the median per-square energy
is 0.010 on clean frames and 0.121 on frames with a hand in view; counting
squares at or over 0.06 flags 36 of 39 hand frames and 0 of 40 clean
frames at a count of 8. That is a usable rule today, before the full
classifier: on settle, if at least 8 squares exceed 0.06, classify the
frame occluded, do not read it, and arm the retake. The three hand frames
it misses still meet the residual gate and strict acceptance. It costs one
comparison on an array the capture already computes, and it removes the
12 to 33 s queue delays and the two hand-frame commits from game 36. It
goes into the plan's Task 3 as one rule with one test (a synthetic energy
array with 8 squares at 0.07 is dropped; with 7 it is read), and is
replaced, not tuned, by the stage 4 classifier.

Still needed from the builder's tables: the energy on the true move's two
squares on clean frames (table 3, I assume). The 0.06 level must sit well
below it or the move-shaped class will miss quiet pawn moves on the far
ranks. If table 3 shows move squares under 0.1, the stage 4 threshold is
set per square from the noise floor (0.01) times a factor, weighted by
projected area, as the state-aware note says, not at a flat 0.06.

## 5. Two housekeeping decisions

- **Section C of the protocol review is to be applied**: the off-board
  class in the trigger (stage 4) and the suspect edge squares in the
  design's ledger section. The builder was right to wait for an explicit
  word; this is it. The design text carries it now; the code comes with
  stage 4.
- **The planning documents and the builder's copy have diverged.** The
  builder could not see the debounce in Task 1 because their copy of the
  plan predates it. The planner's documents live in `aditha-repo` on the
  planning branch; the builder's repo holds a copy. The owner should sync
  `docs/superpowers/` from the planning branch into the builder's repo
  before each builder session (a copy is enough; a git remote is better).
  Until then, the builder should treat the pasted text and the attached
  files from the owner as the current version.

## 6. Asks

1. Owner: the current `eval/RESULTS.md` (tables 2, 3 and 5 of the game 36
   entry, and the sessions 2 to 4 entries). Upload it as before.
2. Owner: sync `docs/superpowers/` into the builder's repo and push the
   builder's branch somewhere with a remote. Work on a branch with no
   remote is one disk failure from gone.
3. Builder: add the interim hand gate to Task 3 as specified in section 4,
   and confirm whether the deployed build now includes Tasks 0 to 3.

## 7. Update, 2026-10-22 evening: builder status and two facts from RESULTS.md

Builder: section C applied in the design; the interim hand gate built and
tested, with a release timeout so an occluded board cannot deadlock the
capture; deployed build 23b7bc4; the branch now has a GitHub remote.

From the results file (the entries up to "what the phone uploads"; the
game 36 tables and the sessions 2 to 4 entries were not in the copy the
planner received):

1. **The phone already uploads a 644 x 644 crop of about 95 KB**, not a
   full still. Upload is not a lever. But the crop is the board's bounding
   rectangle plus 10% margin **squashed** to a square, aspect ratio not
   kept. At the owner's side-on view the board's bounding box is much wider
   than tall, so the squash stretches pieces vertically by a large factor
   on every frame the model sees. The model was not trained on
   anisotropically stretched boards. This is a plausible, untested cause of
   confident wrong readings on individual squares. **Check before
   changing:** on the server, read the example photo and ten recorded
   crops' source frames two ways, squashed and letterboxed (pad to square
   with a neutral border, board centred), and compare per-square maximum
   probability and argmax agreement. If letterboxing is better, the client
   pads instead of squashing; the twin's crop-to-image mapping already
   carries whatever transform is used. One hour, no deploy.
2. **The server is ORT on CPU, 1.2 to 1.4 s warm, 13 s for the first read
   after idle** because the session is created lazily inside the first
   request. At a club evening the first move of the night, and the first
   after any idle gap long enough for the service to restart or unload,
   costs 13 s. Fix: create the inference session at process start, keep it
   for the life of the process, log a `cold: true` flag on any read that
   had to create it, and have the client send one warm-up read at session
   start. Added to the plan's Task 4.

Shift experiment on the unchanged decoder: 12 of 80 position-and-shift
pairs were accepted as moves. That is the quantitative form of section 11
of the brief; Task 0 closes it.

The 2.3 s per read measured on 2026-10-22 01:17 over public HTTPS against
1.3 s on loopback today is unexplained. The debug log's `uploadMs` and
`serverMs` split (Task 4) settles it on the phone; until then no claim
about the network.
