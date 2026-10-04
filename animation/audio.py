#!/usr/bin/env python3
"""Procedural soundtrack for "Six to Picnic" (15 s, 48 kHz stereo, numpy only).

Cue sheet (seconds):
  0.0-1.3  crowd murmur, bowler run-up footsteps, delivery whoosh
  1.30     bat CRACK + crowd roar swelling
  1.35-5.0 slide-whistle arc (up, then down) following the ball
  5.00     plop into the airbox -> engine rev -> lights out -> tyre chirp + launch (5.35)
  5.35-8.6 engine with gear shifts, wind; marshal flag flutter from 7.9
  8.6-9.8  engine dopplers away, flag flutter swells, soft whoosh into the seam
  9.8-11.9 blanket flutter slows, breeze, birds, ukulele enters; fwump as it settles
  12.5     hop-plop; 13.0-13.85 ball rolling; 14.55 pat; 14.6 sparkle arpeggio
"""
import sys, wave
import numpy as np

SR = 48000
DUR = 15.0
N = int(SR * DUR)
T = np.arange(N) / SR
rng = np.random.default_rng(7)

L = np.zeros(N); R = np.zeros(N)

def add(sig, t0=0.0, pan=0.0, gain=1.0):
    """Mix sig (mono) at time t0 with constant-power pan in [-1, 1]."""
    i0 = int(t0 * SR); n = min(len(sig), N - i0)
    if n <= 0: return
    a = (pan + 1) / 2 * np.pi / 2
    L[i0:i0+n] += sig[:n] * gain * np.cos(a)
    R[i0:i0+n] += sig[:n] * gain * np.sin(a)

def env_adsr(n, a=0.005, d=0.05, s=1.0, r=0.1, sr=SR):
    e = np.ones(n); na, nd, nr = int(a*sr), int(d*sr), int(r*sr)
    if na: e[:na] = np.linspace(0, 1, na)
    if nd: e[na:na+nd] = np.linspace(1, s, nd)[:max(0, n-na)]
    e[na+nd:] = s
    if nr and nr < n: e[-nr:] *= np.linspace(1, 0, nr)
    return e

def bandpass(x, lo, hi, soft=0.3):
    """FFT brick-ish bandpass with soft (log-octave) edges."""
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1/SR) + 1e-6
    lf = np.log2(f); m = np.ones_like(f)
    m *= np.clip((lf - np.log2(lo)) / soft + 0.5, 0, 1)
    m *= np.clip((np.log2(hi) - lf) / soft + 0.5, 0, 1)
    return np.fft.irfft(X * m, n=len(x))

def noise(n): return rng.standard_normal(n)

def sweep_tone(f_of_t, n, wave_fn=np.sin):
    ph = np.cumsum(f_of_t) / SR * 2*np.pi
    return wave_fn(ph)

def lin(n, a, b): return np.linspace(a, b, n)

def pluck(freq, dur=0.7, bright=1.0):
    n = int(dur*SR); t = np.arange(n)/SR
    s = np.zeros(n)
    for k in range(1, 7):
        s += np.sin(2*np.pi*freq*k*t + 0.3*k) / (k**1.6) * np.exp(-t*(3.5 + 2.2*k*bright))
    s *= np.exp(-t*2.2) * env_adsr(n, a=0.002, d=0.02, s=1, r=0.05)
    return s * 0.4

def bell(freq, dur=0.8):
    n = int(dur*SR); t = np.arange(n)/SR
    s = np.sin(2*np.pi*freq*t)*np.exp(-t*4) + 0.5*np.sin(2*np.pi*freq*2.76*t)*np.exp(-t*7) + 0.3*np.sin(2*np.pi*freq*5.4*t)*np.exp(-t*10)
    return s * env_adsr(n, a=0.001, d=0.01, s=1, r=0.1)

def thud(f0=140, f1=60, dur=0.18, g=1.0):
    n = int(dur*SR); t = np.arange(n)/SR
    s = sweep_tone(lin(n, f0, f1), n) * np.exp(-t*18) + 0.4*bandpass(noise(n), 80, 600) * np.exp(-t*40)
    return s * g

# ---------------------------------------------------------------- crowd bed (0-9.6 s, fades as we leave the stadium)
n = N
crowd = bandpass(noise(n), 250, 2200, 0.5)
mod = 0.6 + 0.25*np.sin(2*np.pi*0.37*T) + 0.15*np.sin(2*np.pi*0.91*T + 1)
roar = np.interp(T, [0, 1.3, 1.5, 2.2, 3.6, 5.2, 7.0, 9.4, 9.9], [0.22, 0.22, 0.9, 1.0, 0.7, 0.35, 0.22, 0.18, 0.0])
# "wooo" chorus on the six
woo = np.zeros(n)
for f, ph in [(420, 0.0), (520, 1.0), (640, 2.0), (780, 0.5)]:
    woo += np.sin(2*np.pi*f*T*(1+0.01*np.sin(2*np.pi*5.5*T+ph)) + ph)
woo = bandpass(woo, 300, 1500) * np.interp(T, [1.35, 1.6, 2.4, 3.6], [0, 1, 1, 0]) * 0.04
add(crowd*mod*roar*0.16 + woo, 0, 0.0)

# bowler footsteps 0.0-0.8
for k in range(6):
    t0 = 0.05 + k*0.13
    add(thud(120, 70, 0.08, 0.35), t0, pan=0.4 - k*0.1)
# delivery whoosh 0.78-1.25
n = int(0.5*SR); t = np.arange(n)/SR
w = bandpass(noise(n), 400, 3000) * np.sin(np.pi*t/0.5)**2
add(w*0.25, 0.78, pan=0.3)

# CRACK at 1.30
n = int(0.25*SR); t = np.arange(n)/SR
crack = bandpass(noise(n), 1200, 9000, 0.4)*np.exp(-t*70) + 0.5*np.sin(2*np.pi*1900*t)*np.exp(-t*45) + 0.6*thud(260, 90, 0.25)[:n]
add(crack*0.9, 1.30, pan=-0.2)

# slide whistle following the ball: up 1.35->3.15, down 3.15->5.0 (pan L->R)
n = int(3.65*SR); t = np.arange(n)/SR
f = np.where(t < 1.8, 520 + (1500-520)*np.sin(np.pi/2*np.minimum(t, 1.8)/1.8), 1500 - (1500-380)*(np.maximum(t-1.8, 0)/1.85)**1.6)
f = f * (1 + 0.012*np.sin(2*np.pi*6*t))
sw = sweep_tone(f, n) * (0.9*env_adsr(n, a=0.03, d=0.3, s=0.6, r=0.25))
sw += 0.15*bandpass(noise(n), 800, 4000)*np.sin(np.pi*t/3.65)
pan = np.linspace(-0.6, 0.6, n)
i0 = int(1.35*SR); a = (pan+1)/2*np.pi/2
L[i0:i0+n] += sw*0.17*np.cos(a); R[i0:i0+n] += sw*0.17*np.sin(a)

# plop into the airbox at 5.00 (boing-ish)
n = int(0.3*SR); t = np.arange(n)/SR
plop = sweep_tone(lin(n, 330, 70), n)*np.exp(-t*14) + 0.5*bandpass(noise(n), 300, 2500)*np.exp(-t*60)
add(plop*0.8, 5.0, pan=0.2)

# ------------------------------------------------------------------ engine 5.0 -> 9.8
n = int(4.9*SR); t = np.arange(n)/SR  # t0 = 5.0
# rpm curve: idle rev 5.0-5.35, then gears
f0 = np.interp(t, [0, 0.35, 0.36, 1.25, 1.26, 2.05, 2.06, 2.85, 2.86, 3.6, 3.7, 4.9],
                   [70, 165, 110, 300, 215, 330, 240, 345, 262, 350, 330, 150])
# doppler-ish drop after the car passes the camera (~8.6 s => t=3.6)
f0 = f0 * np.interp(t, [0, 3.5, 4.4], [1.0, 1.0, 0.72])
ph = np.cumsum(f0)/SR*2*np.pi
eng = np.zeros(n)
for k, g in [(1, 1.0), (2, 0.7), (3, 0.5), (4, 0.4), (5, 0.28), (6, 0.2), (8, 0.12)]:
    eng += g*np.sin(k*ph + 0.2*k)
eng = np.tanh(eng*1.3)
eng += 0.25*bandpass(noise(n), 300, 2500)*(f0/350)
vol = np.interp(t, [0, 0.3, 0.4, 1.0, 3.4, 3.6, 4.4, 4.8], [0.25, 0.6, 1.0, 1.0, 1.0, 0.8, 0.25, 0.0])
pan = np.interp(t, [0, 3.4, 3.6, 4.6], [0.0, 0.0, 0.5, 0.9])
i0 = int(5.0*SR); a = (pan+1)/2*np.pi/2
L[i0:i0+n] += eng*vol*0.19*np.cos(a); R[i0:i0+n] += eng*vol*0.19*np.sin(a)
# tyre chirp at launch 5.35
n = int(0.25*SR); t = np.arange(n)/SR
chirp = bandpass(noise(n), 1800, 5000)*np.exp(-t*14) + 0.4*sweep_tone(lin(n, 2600, 1800), n)*np.exp(-t*20)
add(chirp*0.25, 5.35)
# wind rush 5.6 -> 9.4
n = int(3.9*SR); t = np.arange(n)/SR
wind = bandpass(noise(n), 150, 1500, 0.6)*np.interp(t, [0, 0.8, 3.0, 3.9], [0, 1, 1, 0])
add(wind*0.12, 5.6)

# ------------------------------------------------------------------ flag -> blanket flutter 7.9 -> 12.0
n = int(4.1*SR); t = np.arange(n)/SR  # t0 = 7.9
rate = np.interp(t, [0, 1.4, 1.9, 2.5, 4.1], [2.7, 2.7, 2.2, 1.7, 1.4])   # flaps per second (slows into the blanket)
gate = 0.5 + 0.5*np.sin(2*np.pi*np.cumsum(rate)/SR)
gate = gate**3
fl = bandpass(noise(n), 350, 3200, 0.5)*gate
lvl = np.interp(t, [0, 0.5, 1.6, 2.0, 2.8, 3.7, 4.1], [0.15, 0.5, 1.0, 0.8, 0.45, 0.2, 0.0])
add(fl*lvl*0.3, 7.9, pan=0.1)
# seam whoosh 9.7-10.6 (big soft swell)
n = int(0.9*SR); t = np.arange(n)/SR
cf = 200*(3000/200)**np.sin(np.pi*t/0.9)
X = noise(n); sw2 = np.zeros(n)
for seg in range(9):
    s0, s1 = int(seg*n/9), int((seg+1)*n/9)
    c = cf[(s0+s1)//2]; sw2[s0:s1] = bandpass(X[s0:s1], c/1.8, c*1.8)[:s1-s0]
sw2 *= np.sin(np.pi*t/0.9)**1.2
add(sw2*0.28, 9.7)
# fwump as the blanket settles 11.85
add(thud(110, 45, 0.3, 0.9)*0.8 + 0, 11.85)
n = int(0.35*SR); t = np.arange(n)/SR
add(bandpass(noise(n), 100, 900)*np.exp(-t*12)*0.35, 11.85)

# ------------------------------------------------------------------ picnic ambience 9.9 -> 15
n = N - int(9.9*SR); t = np.arange(n)/SR
breeze = bandpass(noise(n), 200, 1200, 0.6)*(0.6+0.4*np.sin(2*np.pi*0.23*t))*np.interp(t, [0, 1.0, 5.1], [0, 1, 1])
add(breeze*0.035, 9.9)
# birds
def chirp_bird(t0, base, pan):
    for k in range(3):
        n = int(0.07*SR); t = np.arange(n)/SR
        f = base*(1 + 0.25*np.sin(np.pi*t/0.07)) + k*150
        s = sweep_tone(f, n)*np.sin(np.pi*t/0.07)**1.5
        add(s*0.06, t0 + k*0.11, pan=pan)
for t0, b, p in [(10.6, 3300, -0.6), (11.4, 3900, 0.7), (12.3, 3500, -0.5), (13.4, 4100, 0.6), (14.2, 3600, -0.3)]:
    chirp_bird(t0, b, p)

# ukulele-ish music 10.9 -> 15 (C major pentatonic, 128 bpm)
beat = 60/128
C4, D4, E4, G4, A4, C5, D5, E5, G5 = 261.63, 293.66, 329.63, 392.0, 440.0, 523.25, 587.33, 659.25, 783.99
chords = [[C4, E4, G4], [G4*0.5*1.5, D4, G4], [A4*0.5, C4, E4], [C4*4/3, A4, C5]]  # C, G, Am, F-ish
t0 = 10.9
for bar in range(4):
    for i, f in enumerate(chords[bar]):
        add(pluck(f, 0.9, 0.8), t0 + bar*2*beat + i*0.03, pan=-0.3, gain=0.55)
        add(pluck(f, 0.7, 1.0), t0 + bar*2*beat + beat + i*0.03, pan=-0.3, gain=0.35)
melody = [(0, E5), (0.5, G5), (1.0, A4*2), (1.5, G5), (2.0, E5), (3.0, D5), (3.5, C5), (4.0, D5), (4.5, E5), (5.0, G5), (6.0, E5), (6.5, G5), (7.0, C5*2)]
for bt, f in melody:
    tt = t0 + bt*beat
    if tt < DUR - 0.05: add(pluck(f, 0.8, 1.2), tt, pan=0.3, gain=0.5)
# bass
for bar, f in enumerate([C4/2, G4/4, A4/4, C4*2/3]):
    add(pluck(f, 1.0, 0.5), t0 + bar*2*beat, pan=0.0, gain=0.5)

# hop plop 12.5, ball roll 13.0-13.85, pat 14.55, sparkle 14.6
add(thud(180, 70, 0.2, 0.7), 12.5)
n = int(0.9*SR); t = np.arange(n)/SR
roll = bandpass(noise(n), 90, 500, 0.5)*(0.5+0.5*np.sin(2*np.pi*np.interp(t, [0, 0.9], [9, 2])*t))*np.interp(t, [0, 0.1, 0.7, 0.9], [0, 1, 0.5, 0])
add(roll*0.3, 13.0, pan=-0.4)
add(thud(220, 110, 0.12, 0.6), 14.55, pan=-0.2)
for i, f in enumerate([C5*2, E5*2, G5*2, C5*4]):
    add(bell(f, 0.9)*0.12, 14.6 + i*0.07, pan=-0.3 + i*0.2)

# ------------------------------------------------------------------ master
mix = np.stack([L, R], axis=1)
mix = np.tanh(mix*1.15)/np.tanh(1.15)
mix *= 0.92/np.max(np.abs(mix))
# tiny fade in/out
fi, fo = int(0.05*SR), int(0.25*SR)
mix[:fi] *= np.linspace(0, 1, fi)[:, None]; mix[-fo:] *= np.linspace(1, 0, fo)[:, None]
out = sys.argv[1] if len(sys.argv) > 1 else 'track.wav'
with wave.open(out, 'wb') as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((mix*32767).astype('<i2').tobytes())
print(f'wrote {out}: {DUR}s, peak {np.max(np.abs(mix)):.2f}')
