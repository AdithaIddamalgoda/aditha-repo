# Chess Camera: accounts, game records, leaderboard, and event UX

Design document, 2026-10-17. Builds on the capture app planned in
`docs/superpowers/plans/2026-10-17-chess-camera.md` (static web app, on-device
recognizer, decoder, PGN export). This document adds a backend and the event
features around it. Choices marked **(my call)** were made by the designer, not
stated by the owner, and can be overridden.

## Intent

A chess club holds social evenings in public venues. People walk up to a laid-out
board, sit, play, chat, finish, and the next pair sits down. The owner puts one
phone on a tripod at one table, signed in to the app, and the app records the
games played at that table against the people who played them. Afterwards
everyone can look back at their games, there is a leaderboard for fun, and a
finished game can be shared as an Instagram story card.

## Who is in the room

- **The operator**: the owner, signed in on the table phone. Starts and ends
  games, enters the opponent when the opponent has no account.
- **Players**: club members and strangers. Some will sign in with Google and pick
  a username; many will not on the first evening. Both kinds must be recordable.
- **Spectators**: anyone with the link can watch the table's live board.

## Goals

1. Zero friction at the table: a new game takes one tap and the opponent's name.
2. Every game at the table is stored with both players, the moves, the result,
   and the PGN, and each player can browse their own games.
3. A leaderboard from results, with a few fun stats.
4. Checkmate, stalemate, and dead positions end the game automatically with the
   right result. Resignations and walk-aways are closed with one tap.
5. A good-looking, phone-first interface for the table, history, leaderboard, and
   live board.
6. Downloads stay small by default, with opt-in toggles for the heavier engine
   and the large recognizer.
7. A shareable story card per finished game.

## Non-goals

- Twenty table phones on day one. Nothing here prevents it: recognition is
  on-device and the server only stores moves. It is simply not built or tested
  for launch.
- Tournament pairings, clocks, chat, ratings that anyone takes seriously.
- Public sign-up beyond the club. The app is reachable by link, and sign-in is
  open, but there is no marketing surface.

## Anti-goals (failure even if it works)

- Anything that makes the operator fiddle with the phone between games.
- Capturing anything but the board. No faces, no stored frames by default.
- A leaderboard that one person at the tripod can rig in a minute.
- A first-load download that fails on venue mobile data.

## Constraints carried over

- Recognizer, decoder, capture, licensing, and privacy rules from the existing
  plan stand. The app source is GPL-3.0; the weights are PolyForm Noncommercial.
- Python 3.12 for the backend (owner's language). TypeScript, Vite, no UI
  framework for the web app; the capture module is not migrated to a framework.
- Any Tencent, DNS, or Google Cloud change needs the owner's explicit approval.
- The cricket-daily VM and the EdgeOne-proxied records are never touched.

## The evening, as the app sees it

1. **Setup once per evening.** Operator opens the app, signs in, taps the four
   board corners, and picks the event (name and date). The framing check runs
   against the start position and goes green.
2. **New game.** Players sit and choose colours at the board. Operator taps
   "New game" and picks their own colour. The opponent is attached in one of two
   ways: the table phone shows a QR code and a six-character join code, and the
   opponent scans it, signs in, and taps the free colour; or the operator enters
   them by searching a username or typing a guest name. The table phone shows
   the seat fill in as it happens. Which physical side is White is detected per
   game from the start-position reading, since colours change from game to game
   while the camera does not move.
3. **Play.** Moves are decoded on-device as before. Each accepted ply is sent to
   the server; the live board page updates for spectators.
4. **End.**
   - Automatic: checkmate, stalemate, insufficient material, 75-move rule. The
     result is set without any tap.
   - Board reset: when a live game has at least two plies and a stable frame
     matches the start position, the game is closed as unfinished and the
     operator is asked one question: White won, Black won, draw, or discard.
   - Manual: "End game" button with the same four choices.
   The next game's setup opens immediately with the same event.
5. **Afterwards.** Players sign in from their own phones, claim their guest
   games if they played as a guest, browse their games, see the leaderboard, and
   share a story card.

## Identity and players

- **Sign in with Google** only (Google Identity Services ID token, verified
  server-side with audience check). On first sign-in the person chooses a unique
  username, 3 to 20 characters, letters, digits, underscore, editable later.
- **(owner's decision)** Guests are rated and shown on the leaderboard, and
  can be claimed later. QR self-join ships at launch alongside operator entry.
- **Players are separate from accounts.** A player row has a username and an
  optional linked account. A guest typed by the operator is a player without an
  account. Guest players appear on the leaderboard under the typed name.
- **Claiming.** A signed-in person with no games can claim a guest player by
  name; the operator approves the claim from the admin page. On approval the
  guest player is linked to the account; history and rating carry over.
  **(my call)** Approval goes through the operator because nothing else at a
  social event can verify a name.
- **Join codes.** A game in `setup` has a join code valid for 10 minutes,
  encoded in the QR as `/join/<code>`. Joining needs a signed-in account and a
  free colour; the operator can remove a joined player before the first move.
- **Roles.** The operator's account is admin via an `ADMIN_EMAILS` setting.
  Admin can start games, end games, approve claims, edit results, and delete
  games. Players can view, dispute, claim, and share.

## Game lifecycle and results

- States: `setup`, `live`, `finished`, `discarded`.
- Result: `1-0`, `0-1`, `1/2-1/2`, with reason `checkmate`, `stalemate`,
  `insufficient`, `75-move`, `resignation`, `agreed`, `unfinished`.
- A game needs at least 2 plies to be saved; shorter games are discarded
  silently on reset.
- **Dispute.** A player can dispute a result on a game they played within 7 days.
  A disputed game is hidden from the leaderboard until the admin resolves it.
  **(my call)** This replaces a both-players-confirm step, which would stall
  guests who never sign in.
- **Illegal moves** keep the PGN truncation behaviour from the existing plan; the
  stored game carries the raw move list and the PGN separately.
- **Edit.** Admin can fix a game's result or replace a wrong ply from the game
  page; edits are logged.

## Leaderboard and stats

- Rating: Elo, K = 32, start 1200, draws 0.5, computed in finish order and
  stored per game as before and after. **(my call)**: Elo rather than Glicko
  because it is explainable at a table.
- Rated when both players exist and the game has a result with reason other than
  `unfinished`. Unfinished games with an entered result are rated as well; only
  discarded games are not.
- Leaderboard page: rank, username, rating, games, W/D/L, with filters for
  "this event" and "all time". Ties show the same rank.
- Fun stats per player: longest game (plies), fastest checkmate, current streak,
  and once analysis exists, average accuracy and biggest blunder.
- **Post-game analysis** runs on the server after a game finishes: Stockfish at
  a fixed depth per ply via python-chess, producing centipawn loss per move,
  accuracy per player, and the three biggest swings. Queued, one at a time.
  Shown on the game page as an evaluation graph.

## Live board and story card

- **Live board** at `/live/<table>`: the current game at a table, updated by a
  server-sent event stream, with the move list and the optional eval bar. No
  sign-in needed.
- **Story card** at `/games/<id>/story.png`: 1080x1920 PNG rendered on the
  server with the final position, both usernames, the result, the event name and
  date, and the move count. The game page offers it through the Web Share API,
  with download as fallback. **(my call)** Rendered server-side so the image is
  identical on every phone and can be regenerated.

## Downloads and toggles (Settings page)

| Component | Default | Opt-in toggle | Where it runs |
|-----------|---------|---------------|---------------|
| Recognizer | ChessQ Lite, on-device | "Second opinion from the large model" for uncertain frames | Server, only shown when the server reports it enabled |
| Eval engine | Stockfish lite single-thread build | "Full-strength engine" (large NNUE build) | On-device Web Worker |
| ONNX runtime | WebGPU build with CPU fallback | none | On-device |

- Every download shows its size before starting, is cached by the service
  worker, and can be fetched at home from the Settings page ("Prepare for the
  event") so nothing large is pulled over venue data.
- The large recognizer stays off unless the production box has at least 4 GB of
  memory; the server advertises availability in `/config`.

## Sync, offline, and spectators

- The table phone sends each accepted ply as `POST /games/{id}/moves` with
  `(ply, uci, san, fen, at)`. Idempotent on `(game, ply)`. A local queue retries
  with backoff; a game closed offline sends its result when the connection
  returns. Order is enforced by ply number, not arrival.
- Server emits SSE per table for the live page.

## Backend

- **Stack**: FastAPI, SQLAlchemy 2 + Alembic, SQLite in WAL mode, python-chess,
  Stockfish binary for analysis, Pillow + cairosvg for the story card, uvicorn
  behind Caddy with automatic TLS. **(my call)** SQLite is right for one event's
  scale and one box; a nightly copy of the database file to the owner's existing
  COS bucket is the backup, pending approval.
- **Schema**:
  - `users(id, google_sub unique, email, created_at)`
  - `players(id, username unique, user_id null, created_at)`
  - `events(id, name, date, venue)`
  - `tables(id, event_id, label, operator_user_id)`
  - `games(id, event_id, table_id, white_player_id, black_player_id, status,
    result, reason, rated, started_at, ended_at, ply_count, pgn, raw_moves)`
  - `moves(game_id, ply, uci, san, fen, at, PK(game_id, ply))`
  - `rating_history(id, game_id, player_id, before, after)`
  - `analyses(game_id, depth, json, created_at)`
  - `claims(id, player_id, user_id, status, created_at)`
  - `disputes(id, game_id, player_id, note, status, created_at)`
  - `audit(id, user_id, action, target, at)`
- **API** (JSON, cookie session): `POST /auth/google`, `POST /auth/logout`,
  `GET /me`, `PUT /me/username`, `GET /players/search?q=`, `POST /events`,
  `POST /tables`, `POST /games`, `GET /join/{code}`, `POST /games/{id}/join`,
  `GET /games/{id}/seats/stream`, `POST /games/{id}/moves`,
  `POST /games/{id}/finish`, `GET /games/{id}`, `GET /games?player=`,
  `GET /leaderboard?event=`, `GET /live/{table}/stream`,
  `GET /games/{id}/story.png`, `POST /claims`, `POST /disputes`,
  `GET /config`, admin routes under `/admin`.
- **Security**: HttpOnly Secure SameSite=Lax session cookie, 30 days; a custom
  request header on mutating calls; per-IP rate limits on auth and search; only
  the table's operator or an admin can post moves or finish a game; images are
  never accepted by any endpoint except the optional large-recognizer `/read`,
  which holds them in memory only.
- **Privacy**: account deletion anonymises the player's username to
  "deleted player" and keeps the games. Stated on the sign-in screen.

## Hosting

**(owner's decision, 2026-10-17)** A new small Lighthouse instance in Singapore for
production: 2 vCPU, 2 GB, Ubuntu 22.04, Caddy + the backend + the static app +
the model and runtime files on one box, firewall 443 and 80 open, SSH restricted
to the owner's address range with the console terminal as fallback. The dev VM
stays private. `chess.banis.ink` is a plain A record at DNSPod and does not
depend on the EdgeOne plan. A 4 GB instance instead enables the large
recognizer. Lighthouse bandwidth is capped, so the first-load download of about
92 MB per new phone takes around 40 seconds; the "Prepare for the event" step
exists for that reason.

Alternative if no new box: the same stack on the dev VM, with the same hardening
first. It works, but it exposes the box the owner develops on.

Google: an OAuth client in a Google Cloud project owned by the owner, with the
production origin and `http://localhost:5173` as authorised origins. The owner
creates it; the builder cannot.

## Interface

Pages: Sign in, Table (setup, new game, live capture, end game), Game (board
replay, move list, eval graph, share), My games, Leaderboard, Player profile,
Live board, Settings, Admin (claims, disputes, edits).

Direction for the builder: phone-first, one hand, dark and light themes from a
single token set, large tap targets at the table, the board always the biggest
thing on screen, states visible at a glance (reading, pending, needs you). Use
the design skills available in the session for the visual direction, interface
feel, accessibility, and the evaluation graph. Keep the capture screen's logic
untouched; restyle around it.

## Left to the builder

- Router and templating approach within vanilla TypeScript.
- Exact Elo tie-breaking and the stats queries.
- Story card layout, within the fixed fields above.
- Analysis depth and queue implementation.
- Service worker versioning and cache eviction.

## Order of delivery

1. Backend core: auth, players, events, tables, games, join codes, moves,
   finish, config. Table phone sends moves. Live board.
2. Game end automation and board-reset detection on the phone; result prompt.
3. History, leaderboard, rating, claims, disputes, admin.
4. Settings page with the download toggles and "Prepare for the event".
5. Interface pass over every page with the design skills.
6. Post-game analysis and the story card.
7. Production box, DNS, Google client, deploy, backup. Each with approval.

## Addendum, 2026-10-18: board detection without taps, and the 3D twin

Field test on 2026-10-17: tapping four corners on a phone is too fiddly, there
is no undo, and the side-on tripod angle makes pieces hide each other. The
research in `docs/superpowers/research/2026-10-18-chess-recognition-angles.md`
found that neither published model uses state, rules, time, or occlusion, and
that no paper reports accuracy per camera angle. This addendum adds two things
to the design. They go in the next plan ahead of the accounts work, because the
table flow depends on them.

### Start with no taps

- The recognizer runs once on the Start frame with attention outputs enabled.
  Each of its 64 square queries has an attention centroid in the image. A
  homography is fitted from the ideal square centres to those centroids with
  RANSAC; at least 48 of 64 inliers are required.
- The grid is drawn over the camera view. It is accepted automatically when the
  start-position reading goes green under some rotation. Otherwise the four
  corners become large draggable handles with a magnifier loupe, an undo stack,
  and "find again".
- The grid is re-fitted automatically when bump detection fires.
- The app picks the phone's main rear camera by device id, never the ultrawide,
  and shows the camera elevation estimated from the grid with a hint when it is
  below 50 degrees. Target 55 to 65 degrees.
- ChessQueries' own corner detector is not used; the paper reports it fails on
  most ChessReD photos. A learned corner model is a fallback only if the
  attention fit fails on the owner's photos, and would train on the rendered
  and ChessReD2K corner labels listed in the research notes.

### The 3D twin (analysis by synthesis)

The decoder already has the state and transition model: the position is known
exactly at the start, and only legal moves, undos, two-ply skips, and rare
illegal moves can follow. The twin adds a second observation channel that is
independent of the learned recognizer and reasons about occlusion explicitly.

- **Camera.** The grid homography plus the focal length recovered from the two
  vanishing points of the grid lines gives a full camera pose. Wobble is
  handled by re-estimating the homography each frame from the board texture.
- **Pieces.** Each type is a cylinder of a height and radius in square units,
  standing on its square centre; projecting it gives a silhouette mask. Default
  dimensions follow Staunton proportions; per-set calibration from the start
  frame is a later improvement.
- **Visibility.** For a state, the painter's-order render gives each piece's
  visible fraction `v_s`. The recognizer's log-probability on square `s` is
  weighted by `v_s`, so hidden squares stop voting.
- **Silhouette change.** For a candidate state, the predicted change mask is
  the XOR of its render with the previous state's render. The observed change
  mask is the thresholded, brightness-normalised difference between the two
  stable frames. The score is the intersection over union in the union region.
  Textures and lighting are never modelled.
- **Posterior.** `log P(s_t) = Σ_s v_s · lp_s + λ · IoU + log prior(tier)`. The
  decoder keeps a beam of the top three hypotheses so an ambiguous move
  resolves on the next frame. Expected change masks for all legal replies are
  rendered during the opponent's thinking time.
- **Cost.** Masks are a few polygons on a 128-pixel crop; thirty candidates
  take well under a millisecond each. When the silhouette term alone leaves one
  candidate with a wide margin, the recognizer is confirmation only and can be
  skipped, which cuts latency.
- **Tooling.** Whether to hand-roll the projection and masks or use an existing
  library is decided by `docs/superpowers/research/2026-10-18-3d-twin-tooling.md`
  before the twin tasks start. The default, pending that file, is hand-rolled
  projection with no new dependency.
- **Gate.** On the recorded corpus, the combined scorer must beat the
  recognizer-only decoder on silent errors and prompts, measured with
  recognizer-only, silhouette-only, and combined runs. If it does not, the
  twin stays as the visibility weighting only.

### The data flywheel

Every photo in a finished game has a known position once the PGN is confirmed.
An adapter turns the corpus into the dataset format the ChessQueries few-shot
LoRA script expects. A fine-tuned large model serves as the server second
opinion; a fine-tuned Lite is distilled for the phone later. Training runs on
the dev VM overnight or on a rented GPU for an hour with approval.

### Order of delivery, revised

0. This addendum: auto-grid, camera guidance, twin spike and integration,
   corpus adapter and first fine-tune.
1. to 7. as above.
