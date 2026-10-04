# Character sprite brief — "Six to Picnic"

Project: the cricketer → F1 car → Haaland picnic showreel in this repo (`six_to_picnic.mp4`, source in `animation/`).
Purpose: replace the hand-drawn vector characters in `animation/scene.html` with generated 2D sprites.
The animation rig stays as it is; it swaps whole-body key poses per character and keeps the camera moves,
squash-and-stretch, the ball, the checkered cloth and all effects. So every sprite must be a clean,
isolated, consistently sized character on an empty background.

## 1. Repo and branch

- Clone, do not `git init` elsewhere: `git clone https://github.com/AdithaIddamalgoda/aditha-repo.git`
- Branch: `claude/funny-keller-thmx75` (check it out; do not push to main)
- Put files under `animation/sprites/<character>/<pose>.png` exactly as named in section 4
- Commit only the PNGs (and nothing from `~/.config`), then push the same branch

## 2. Style (identical for every image)

Use this prefix verbatim on every prompt:

> Cute flat 2D cartoon character, simple geometric shapes, very big round head (about 40% of total height),
> tiny dot eyes with a white highlight, small pink blush, thick dark outline (#2b2640), flat pastel fills,
> no gradients, no shading except one soft cheek blush, clean vector look. Full body, side view facing RIGHT,
> feet resting on an invisible floor at the bottom of the image, character centered, fills about 85% of the
> image height. Plain solid white background, nothing else in frame, no text, no logos, no shadow.

Rules:
- White background (#ffffff), not transparent. The rig keys it out; a flat white is more reliable than alpha
  from the model. No drop shadows, no ground line.
- Square 1024×1024 output, one character per image.
- Same scale for every pose of the same character: head size and body proportions must not change between poses.
- Consistency: generate the `neutral` pose first, get it approved, then produce every other pose of that
  character with image-to-image / edit mode using the approved neutral PNG as the reference image, prompt
  "same character, same style, same colors, same proportions, now in this pose: …". Nano Banana 2 is the
  right default for this.
- Facing: all characters face RIGHT except the bowler, who faces LEFT.
- Caricatures only, no real likenesses or real logos: "a tall blond footballer in a plain sky-blue shirt with
  a white number 9", "a navy racing car with red and yellow accents".

## 3. Characters

| id | description to append after the style prefix |
|----|-----------------------------------------------|
| `batter` | a cricket batter in all-white kit, navy helmet with a face grille, white leg pads, holding a tan wooden cricket bat |
| `bowler` | a cricket bowler in all-white kit, short dark brown hair, no helmet, FACING LEFT |
| `marshal` | a race marshal in an orange hi-vis vest with two pale yellow stripes, white cap, dark trousers, holding a plain white pole in the raised hand (NO flag on the pole; the flag is drawn by the rig) |
| `footballer` | a very tall blond footballer, hair swept back into a small top bun, thin dark headband, sky-blue shirt with a white number 9 on the chest, white shorts, sky-blue socks, white boots, long legs |
| `car` | a navy open-wheel racing car with red nose and yellow stripe accents, red-helmeted driver visible in the cockpit, a dark oval air intake opening on top directly behind the driver's head, big rear wing, side view facing RIGHT, NO wheels (empty wheel arches), on a white background |
| `wheel` | one single racing wheel seen from the side: black tyre, light grey five-spoke rim with a small red hub, centered, white background |

## 4. Poses and exact file names

Generate `neutral` first for each character; the rest via edit mode from it.

```
animation/sprites/batter/neutral.png        standing stance, bat held low behind the body, slight knee bend, calm smile
animation/sprites/batter/backlift.png       bat raised high behind the shoulder, weight back, eyes wide, concentrating
animation/sprites/batter/contact.png        mid-swing, bat horizontal in front at waist height, gritted teeth
animation/sprites/batter/follow.png         follow-through, bat pointing up and forward over the shoulder, mouth open
animation/sprites/batter/celebrate.png      both arms raised, bat held up in one hand, big happy closed-eye grin

animation/sprites/bowler/neutral.png        running stride, one arm forward, holding a small red ball, FACING LEFT
animation/sprites/bowler/release.png        delivery stride, bowling arm straight up overhead, FACING LEFT
animation/sprites/bowler/duck.png           crouched down covering head with both arms, worried face, FACING LEFT

animation/sprites/marshal/neutral.png       standing, one arm raised straight up holding the pole, other arm relaxed, grin
animation/sprites/marshal/cheer.png         same but hopping slightly, both feet off the floor, happy closed eyes

animation/sprites/footballer/neutral.png    standing tall, both arms raised straight up above the head as if holding a blanket by its top corners, hands open, mouth in a small "o"
animation/sprites/footballer/release.png    standing tall, arms relaxed at sides, big open grin
animation/sprites/footballer/hop.png        small jump, knees tucked, arms slightly out, delighted
animation/sprites/footballer/sit.png        sitting on the floor with legs crossed, hands resting on knees, content smile
animation/sprites/footballer/reach.png      sitting, leaning far to the LEFT, left arm stretched down to the floor beside him, right hand on knee, curious raised eyebrow
animation/sprites/footballer/thumbs.png     sitting upright, right hand thumbs-up at shoulder height, happy closed-eye grin

animation/sprites/car/neutral.png           the car, no wheels
animation/sprites/wheel/neutral.png         the wheel
animation/sprites/ball/neutral.png          a cricket ball: red leather, white stitched seam curving across it, small white highlight, centered, white background
```

21 images in total. One variant each. Test with `footballer/neutral.png` first and get approval, then run the rest.

## 5. What happens next

Once the PNGs are on the branch, the cloud session will:
1. key out the white, auto-crop and register each pose to a common baseline and scale per character;
2. swap the sprites into `scene.html` (pose selection by time, with short cross-dissolves and the existing
   squash-and-stretch), attach the cricket ball, the bat trail, the flag cloth and the blanket to measured
   hand/airbox anchor points;
3. re-render `six_to_picnic.mp4` with the same Playwright + ffmpeg pipeline, same 15 s / 1080p60 / under 30 MB.
