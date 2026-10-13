#!/usr/bin/env python3
"""Smoke test: render scrolling code frames, run OCR + consolidation, compare to ground truth.
Usage: python tests/make_synthetic_test.py   (run from the skill root)"""
import os, subprocess, sys, tempfile, glob
from difflib import SequenceMatcher
from PIL import Image, ImageDraw, ImageFont

CODE = ["import os", "def load(path):", "    with open(path) as f:", "        data = f.read()",
        "    return data.split('x')", "", "for line in load('a.txt'):", "    print(line.strip())"]
fonts = [f for f in glob.glob('/usr/share/fonts/**/*Mono*.ttf', recursive=True)
         + glob.glob('/System/Library/Fonts/*Mono*') + glob.glob('C:/Windows/Fonts/consola.ttf')
         if 'Bold' not in f and 'Italic' not in f and 'Oblique' not in f]
if not fonts:
    sys.exit("no monospace font found; skip synthetic test and use a real video")
font = ImageFont.truetype(fonts[0], 22)
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.makedirs(f"{tmp}/frames")
for k in range(len(CODE) - 4):
    im = Image.new('RGB', (800, 200), (30, 30, 30)); d = ImageDraw.Draw(im)
    for i, l in enumerate(CODE[k:k + 5]):
        d.text((10, 10 + i * 32), l, font=font, fill=(220, 220, 220))
    im.save(f"{tmp}/frames/f_{k:03d}.png")
py = sys.executable
subprocess.run([py, f"{root}/scripts/ocr_frames.py", f"{tmp}/frames", "--out", f"{tmp}/ocr", "--fps", "1", "--dedupe", "0"], check=True)
subprocess.run([py, f"{root}/scripts/consolidate.py", f"{tmp}/ocr", "--out", f"{tmp}/code.txt"], check=True)
got = [l for l in open(f"{tmp}/code.txt").read().split("\n") if l.strip()]
exp = [l for l in CODE if l.strip()]
ratio = SequenceMatcher(None, "\n".join(exp), "\n".join(got)).ratio()
print("\n".join(got)); print(f"similarity vs ground truth: {ratio:.3f}")
sys.exit(0 if ratio > 0.95 else 1)
