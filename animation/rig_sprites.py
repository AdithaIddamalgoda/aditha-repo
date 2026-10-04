#!/usr/bin/env python3
"""Prepare generated sprites for the scene rig.

For every animation/sprites/<char>/<pose>.png:
  * key the white background to alpha with a flood fill from the image border
    (a global white key would also delete the white cricket kit),
  * soften the one-pixel fringe,
  * crop to the opaque bounding box,
  * record size, the topmost opaque pixel (pole top for the marshal) and the
    position of any pink cricket ball baked into the pose (bowler),
  * for the bowler also write a "noball" variant with that ball erased,
  * write everything to animation/rigged/ plus rigged/manifest.json.
Outputs are build intermediates (gitignored); rebuild with build.sh.
"""
import json, os, glob
import numpy as np
from PIL import Image, ImageDraw

SRC = os.path.join(os.path.dirname(__file__), 'sprites')
DST = os.path.join(os.path.dirname(__file__), 'rigged')
SENT = (255, 0, 255)

# Hand-measured anchors in normalized coordinates of the CROPPED sprite (x/w, y/h).
ANCHORS = json.load(open(os.path.join(os.path.dirname(__file__), 'anchors.json'))) if os.path.exists(os.path.join(os.path.dirname(__file__), 'anchors.json')) else {}

def key_white(im):
    rgb = im.convert('RGB')
    w, h = rgb.size
    seeds = [(0, 0), (w-1, 0), (0, h-1), (w-1, h-1), (w//2, 0), (w//2, h-1), (0, h//2), (w-1, h//2)]
    for s in seeds:
        if rgb.getpixel(s) != SENT:
            ImageDraw.floodfill(rgb, s, SENT, thresh=70)
    a = np.array(rgb).astype(np.int16)
    bg = (a[..., 0] == 255) & (a[..., 1] == 0) & (a[..., 2] == 255)
    src = np.array(im.convert('RGB')).astype(np.int16)
    alpha = np.where(bg, 0, 255).astype(np.uint8)
    # soften fringe: opaque pixels touching background get alpha from their darkness
    pad = np.pad(bg, 1)
    near = (pad[:-2, 1:-1] | pad[2:, 1:-1] | pad[1:-1, :-2] | pad[1:-1, 2:]) & ~bg
    mn = src.min(axis=2)
    soft = np.clip((255 - mn) * 255 / 110, 0, 255).astype(np.uint8)
    alpha = np.where(near, np.minimum(alpha, np.maximum(soft, 40)), alpha)
    out = np.dstack([src.astype(np.uint8), alpha])
    return out

def find_ball(rgba):
    r, g, b, a = [rgba[..., i].astype(np.int16) for i in range(4)]
    m = (a > 128) & (r > 190) & (g < 150) & (b < 175) & (r - g > 60)
    if m.sum() < 400:
        return None, m
    ys, xs = np.nonzero(m)
    # keep the densest blob: use the median as centre and radius from area
    cx, cy = float(np.median(xs)), float(np.median(ys))
    rad = float(np.sqrt(m.sum() / np.pi)) * 1.25
    return (cx, cy, rad), m

def erase_ball(rgba, ball):
    cx, cy, rad = ball
    h, w = rgba.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.hypot(xx - cx, yy - cy)
    out = rgba.copy()
    out[d < rad + 4, 3] = 0
    return out

def crop(rgba):
    a = rgba[..., 3]
    ys, xs = np.nonzero(a > 8)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    return rgba[y0:y1, x0:x1], (x0, y0)

manifest = {}
for path in sorted(glob.glob(os.path.join(SRC, '*', '*.png'))):
    char = os.path.basename(os.path.dirname(path)); pose = os.path.splitext(os.path.basename(path))[0]
    rgba = key_white(Image.open(path))
    ball, _ = find_ball(rgba) if char == 'bowler' else (None, None)
    variants = {pose: rgba}
    if ball:
        variants[pose + '_noball'] = erase_ball(rgba, ball)
    for name, arr in variants.items():
        c, (ox, oy) = crop(arr)
        h, w = c.shape[:2]
        os.makedirs(os.path.join(DST, char), exist_ok=True)
        Image.fromarray(c, 'RGBA').save(os.path.join(DST, char, name + '.png'), optimize=True)
        a = c[..., 3]
        top_y = int(np.argmax((a > 128).any(axis=1)))
        top_x = float(np.nonzero(a[top_y] > 128)[0].mean())
        band = a[int(h * 0.92):] > 128
        ys_b, xs_b = np.nonzero(band)
        feet_x = float(xs_b.mean()) / w if len(xs_b) else 0.5
        entry = {'w': w, 'h': h, 'anchors': {'top': [top_x / w, top_y / h], 'feet': [feet_x, 1.0]}}
        if ball:
            entry['anchors']['ball'] = [(ball[0] - ox) / w, (ball[1] - oy) / h, ball[2] / w]
        for k, v in ANCHORS.get(char, {}).get(pose, {}).items():
            entry['anchors'][k] = v
        manifest.setdefault(char, {})[name] = entry
json.dump(manifest, open(os.path.join(DST, 'manifest.json'), 'w'), indent=1)
open(os.path.join(DST, 'manifest.js'), 'w').write('window.SPRITE_MANIFEST=' + json.dumps(manifest) + ';')
print(json.dumps({c: {p: (e['w'], e['h'], {k: [round(x, 3) for x in v] for k, v in e['anchors'].items()}) for p, e in ps.items()} for c, ps in manifest.items()}, indent=0)[:4000])
