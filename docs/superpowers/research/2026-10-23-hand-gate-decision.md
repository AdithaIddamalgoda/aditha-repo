# Deploy decision: the hand gate after A1 to A5

Written 2026-10-23 by the planner from the builder's follow-up entry in
`eval/RESULTS.md` (HEAD 554b4d3) and the five commits. Question from the
owner: revert A3 (the check-only release) or fix its cause first, and do not
decide blindly.

## 1. What the replay proves and what it does not

Proved: with A1 to A4, the replay has 0 illegal-tier commits and 0 wrong
commits on all three games, and game 36 recovers all 22 plies. The first
wrong commit of every recorded cascade is gone. That part is settled.

Not proved: that A1 and A2 alone stop the wrong commits. The replay was run
only with the full set. The one hand-frame commit we can reason about, game
36's `f3g1` at 61.8 s (score 12.2, residual 2, both squares strongly
agreeing), is a legal move with strong evidence on each square: A1 does not
touch it and A2 (per-square floor 1.0) does not block it. So "revert A3 and
let A1 and A2 guard the old release" (the builder's option 1) is a claim,
not a result. It needs its own replay row before anyone deploys it.

Also not proved: why game 39's clean frames are busy. The entry says frames
#27 to #30 are clean anchors at 48, 46, 53 and 51 busy squares against the
reference with no picture shift, and calls it lighting. Two mechanisms fit
that sentence and need different fixes:

- **Frame-to-frame change** (auto exposure or white balance swinging, a
  shadow moving): consecutive clean frames also differ on many squares. Fix:
  a change measure that ignores smooth illumination (section 3), and lock
  exposure where the camera allows it.
- **A stale or poisoned reference**: consecutive clean frames agree with each
  other within a few squares, but all differ from a reference taken under
  other lighting, or from a hand frame that the check-only path adopted
  because the model read through the hand. Fix: the reference policy
  (section 3), not the measure. Note that the replay's check-only path
  re-references on agreement without the busy-square test that A4 applies
  to judged frames, so a hand frame the model reads correctly can become the
  reference by that route. The 4 agreed check reads in game 39 are the
  frames to look at.

One hour of the builder's time on the existing crops tells which, and the
answer picks the fix. That is the measurement the owner asked for before
anyone calibrates anything.

## 2. The diagnostic (game 39 crops, throwaway script, numbers into RESULTS)

For every pair of consecutive clean anchor frames in game 39, and for the
same in games 36 and 38 as controls:

1. Busy squares (energy at or over 0.06) between the two consecutive frames,
   not against the reference. If the median is under 8, the measure is fine
   and the reference policy is the fault; if it is 20 or more, the scene
   changes between frames and the measure is the fault.
2. The board's mean grey per clean frame over the session, as a line, and
   the mean of the light squares and of the dark squares separately. A
   swinging mean is auto exposure; light and dark squares moving by
   different ratios is a gamma or white-balance change that the current
   per-frame mean normalisation cannot remove.
3. For the 4 check reads that agreed in the replay: the seq numbers and, by
   eye, whether a hand or arm is in the crop.
4. For one clean pair with 45 or more busy squares: the 8 x 8 map of the
   per-square ratio cur/prev. Smooth across the board means illumination;
   a patch means a shadow or an object.

## 3. The fixes, each tied to a diagnostic outcome

- **Reference policy** (if 2.1 says consecutive frames agree). The reference
  may be refreshed only by a frame that passes the busy-square test against
  the *previous settled frame* as well as `Decoder.check`; a held frame that
  agrees with the board but is busy against the previous frame is a hand the
  model read through, and stays out. And the check-only path must be allowed
  to catch up: check against the committed state and its legal continuations
  up to two plies (the `twoply` candidates already exist), committing when
  exactly one matches at residual 0. That is the smallest piece of the
  design's anchor search and it ends the "101 refusals" stall, because the
  decoder advances with the held frames instead of falling behind them.
- **Illumination-robust energy** (if 2.1 says consecutive frames differ).
  Cheapest version first: the grid says which squares are light and which
  are dark, so normalise each square's ratio by the median ratio of its own
  colour class instead of by the whole-board mean. A gamma or exposure
  change moves both class medians and cancels; a moved piece changes two to
  four squares away from their class median and survives. Second version if
  that is not enough: energy on gradient magnitude (edges) instead of
  intensity, since piece outlines and square borders survive lighting
  changes that intensities do not. Both are a few lines in `squareEnergy`
  and are testable offline on all four games with the labels that exist.
- **Exposure lock** (if 2.2 shows swings). `lockExposure` only applies when
  the camera reports manual exposure. Record the track's capabilities and
  settings in `session.json` so we know what this phone offers, and try
  `exposureMode: 'manual'` plus `whiteBalanceMode: 'manual'` after the
  start check, when the picture is at its best.

## 4. What to deploy for the recording sessions, and why neither option as stated

Protocol v2's labels come from the script, not from the decoder, so for S0
to S3 the decoder's accuracy matters less than the completeness of what is
saved. The server stores only crops that were read. A gate that holds frames
therefore throws away the frames the gate is supposed to be designed from:
with A3 as it stands, a session lit like game 39 would save 3 crops in 20
minutes. Reverting to the old release (option 1) saves more but still holds
for up to 3 s and may commit hand frames the replay has not cleared.

So, for the recording sessions only:

- Deploy A1, A2, A4, A5, the lockfile, the warm-up and cold flag.
- Deploy the hand gate in **shadow mode**: compute the verdict and the busy
  count on every settle, log them (`occluded` with `held: false`), but read
  every settled frame. Nothing is held, nothing is released, the check-only
  path is not reached. Every frame the owner records is saved with the
  gate's opinion of it attached.
- Keep the retake on pending and badframe as they are.
- Operator cost: hand frames are read (1.3 s each) and a few may commit
  wrongly despite A1 and A2; the owner corrects the PGN at End session as
  the protocol says, and Undo is unlimited. For a 90-minute recording that
  is acceptable; for a club evening it is not, and that is the point of the
  recordings.

After S0 to S3 and the section 2 diagnostic, the gate is designed offline
on five games (36 to 39 plus the scripted ones), evaluated by the replay
harness, and only then does it hold frames in production. The harness
should be committed, not thrown away: it is now the project's primary test
of the capture policy and it has been rewritten three times.

## 5. Decision

Option 2, with these two amendments: nothing holds frames in production
until the gate is designed on complete data, and the deploy for the
recordings runs the gate in shadow mode with A1, A2, A4 and A5 live.
Option 1 is not taken because its safety is asserted, not replayed, and
because any hold loses the recordings we need.

## 6. For the builder

1. Section 2's four diagnostics on game 39 (controls: 36 and 38) into
   RESULTS. One hour. The result says whether section 3's first or second
   fix comes first.
2. Replay option 1 as a row (old release, A1, A2, A4, no A3) so the claim is
   measured; if it shows wrong commits, say so in RESULTS and the option is
   closed.
3. Shadow mode for the gate behind a config flag (`holdOccluded: false` for
   this deploy), `occluded` events carrying `count` and `held`, track
   capabilities and settings in `session.json`, and the replay harness
   committed under `web/scripts/replay.ts` with the three games as its
   fixtures.
4. Deploy from a clean tree; confirm the hash to the owner before S0.
5. A6 (self-calibration), A7 (occlusion before bump), A8 (release budget)
   remain open and are not needed before the recordings.

C1 (masking the margin) is closed by the data: no change. C3 confirms the
grid offset varies by view, which is the case for A6 and for the twin plan's
visibility weights to wait until the grid is calibrated per session.
