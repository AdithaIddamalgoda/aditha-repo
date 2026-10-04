# Six to Picnic

A 15-second 2D cartoon (1920×1080, 60 fps, stereo sound) in which one object carries the audience
through three worlds without a single cut:

| Time | Beat | How the seam is carried |
|------|------|-------------------------|
| 0–5 s | Cricketer hits a six; the camera rides the ball's arc up and over the stadium. | The ball's parabola *is* the camera path. |
| 5 s | Ball drops into the airbox of a navy F1 car on the start grid. | The ball's bounce becomes the car's squash-and-rev; the start lights go out and the car launches. The camera never stops tracking the ball, which is now part of the car. |
| 5–10 s | Car tears down the straight to the finish; the marshal's checkered flag is waved and swells to fill the frame. | The flag is one waving cloth mesh that scales up in place until the screen is pure checkered pattern. |
| 10 s | Pull back from the pattern: it is a blanket in mid-air held by a tall blond footballer. | Same mesh, same wave phase; the flag's flutter decays into the blanket's flutter as it settles on the grass. |
| 10–15 s | He flicks the blanket out, hops onto it, and a corner keeps flapping, until the cricket ball rolls in from the left and he pins the corner with it. | The ball callback stitches all three worlds into one. |

Deliverable: [`six_to_picnic.mp4`](six_to_picnic.mp4) (H.264 + AAC, ~8.5 MB).

## Pipeline (Playwright + ffmpeg frame render)

- `animation/sprites/` holds the generated character art (19 PNGs: batter, bowler, marshal, footballer, car, wheel, ball), made to the spec in `animation/CHARACTER_BRIEF.md`.
- `animation/rig_sprites.py` keys the white backgrounds with a border flood fill (so the white cricket kit survives), crops, finds feet/pole-top/ball anchors, erases the baked-in ball for the bowler's post-release frames, and writes `animation/rigged/` plus a manifest. Hand-measured anchors (hands, bat, airbox, wheel arches) live in `animation/anchors.json`.
- `animation/scene.html` draws any frame as a pure function of time on a 1920×1080 canvas. Characters are the rigged sprites, switched pose-to-pose with short dissolves; the ball launch point, the airbox landing, the flag attachment and the blanket's hand corners are all read from the sprite anchors. Open it with `?t=7.5` in a browser (file access flag needed) to inspect a moment.
- `animation/render.js` drives headless Chromium through 900 timestamps and pipes each PNG straight into one `ffmpeg` libx264 encode. No frame sequence or lossless master is written anywhere.
- `animation/audio.py` synthesizes the whole soundtrack with numpy: crowd, bat crack, slide-whistle ball arc, engine with gear shifts and doppler, flag and blanket flutter, birds, breeze, ukulele-style plucks and the sparkle at the end.
- `animation/build.sh` runs the three steps and prints the ffprobe summary.

Requirements: Node 22 with `playwright` (Chromium installed), `ffmpeg` with libx264/aac, Python 3 with `numpy` and `Pillow`.

Characters are deliberate caricatures (navy car with red/yellow accents, tall blond number 9 in sky blue); no real logos or likenesses are used.
