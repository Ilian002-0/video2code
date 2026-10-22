---
name: video2code
version: 1.0.0
description: Extract verified source code, config, or decompiled snippets from programming tutorial videos, conference talks, or reverse-engineering walkthroughs using dense OCR alignment and voting. Do NOT use for general video summarization without on-screen code.
allowed-tools:
  - bash
  - read
  - write
metadata:
  author: Ilian002-0 <https://github.com/Ilian002-0>
  tags:
    - video
    - ocr
    - code-extraction
    - reverse-engineering
    - developer-tools
---

# video2code (Video Code Extractor)

Reconstruct source code displayed on screen in videos (tutorials, screencasts, conference talks, reverse-engineering sessions) as real, runnable files, with an explicit report of every ambiguous line.

## Purpose

Standard video models provide text summaries or sparse frame captures, which flatten indentation, lose lines scrolled out of view, and fail on compression artifacts. `video2code` implements the research approach from *"Extracting Code from Programming Tutorial Videos"* (ACE, Onward! 2016): dense sampling, geometry-aware OCR, multi-frame alignment, and confidence-weighted voting combined with syntax verification.

## Prerequisites

- **System Tools**: `yt-dlp`, `ffmpeg`, and `tesseract` (or `easyocr` via PyTorch).
- **Python Libraries**: `pip install pytesseract pillow rapidfuzz` (and optionally `pip install easyocr`).

## Available Scripts

| Script | Purpose | Key Arguments |
|---|---|---|
| `scripts/ocr_frames.py` | Runs OCR on dense video frames, preserves indentation geometry, and filters near-identical frames. | `--out <dir>`, `--fps <num>`, `--t0 <sec>`, `--crop <x,y,w,h>`, `--scale <num>`, `--engine <auto\|tesseract\|easyocr>` |
| `scripts/consolidate.py` | Aligns all frame lines into a single document via dynamic programming and weighted voting. | `<ocr_dir>`, `--out <file.txt>`, `--report <uncertain.json>`, `--min-sim <0.0-1.0>` |
| `tests/make_synthetic_test.py` | Standalone test that renders synthetic scrolling code frames to verify OCR and alignment without video download. | Run directly with `python tests/make_synthetic_test.py`. |

---

## Pipeline

Work directory convention: `WORK=./vce_work`.

### 0. Quick Check for Existing Repositories
Check video metadata for public repository or Gist links:
```bash
yt-dlp --dump-json --skip-download "<url>"
```
If an official repository exists in the description, use it directly and use the video only for navigation.

### 1. Download Video and Subtitles
```bash
yt-dlp -f "bv*[height<=1080]+ba/b[height<=1080]" -o "$WORK/video.%(ext)s" "<url>"
yt-dlp --skip-download --write-auto-subs --sub-langs "en.*,fr.*" --convert-subs srt -o "$WORK/sub" "<url>"
```
Prefer 1080p when available to maximize OCR character resolution.

### 2. Identify Code Segments
Identify time intervals where an IDE, terminal, or code slide is displayed using transcript keywords or sparse sampling:
```bash
ffmpeg -i "$WORK/video.mp4" -vf "fps=1/10" "$WORK/map/m_%05d.png"
```
Determine the start and end timestamps (`start_time`, `end_time`) for each code segment.

### 3. Determine Editor Crop Region
Inspect a representative frame to determine the bounding box `x,y,w,h` of the code editor (excluding sidebars, webcams, and taskbars).

### 4. Extract Dense Frames
```bash
ffmpeg -ss <start> -to <end> -i "$WORK/video.mp4" -vf "fps=2" "$WORK/frames/seg1/f_%05d.png"
```
Use `fps=2` for live typing and `fps=1` for slides or scrolling.

### 5. Run Geometry-Aware OCR
```bash
python scripts/ocr_frames.py "$WORK/frames/seg1" --out "$WORK/ocr/seg1" --fps 2 --t0 <start> --crop x,y,w,h --scale 2
```
Generates structured JSON per distinct frame with indentation reconstructed from word coordinates.

### 6. Consolidate and Vote Across Frames
```bash
python scripts/consolidate.py "$WORK/ocr/seg1" --out "$WORK/code_seg1.txt" --report "$WORK/uncertain_seg1.json"
```
Aligns frames into a unified document and performs confidence-weighted voting. Ambiguous lines are recorded in `uncertain_seg1.json`.

### 7. Three-Level Verification

- **Token level**: Harmonize identifiers against project vocabulary and spoken transcript.
- **Line level**: Validate balanced brackets, quotes, colons, and indentation consistency.
- **Fragment level**: Verify code with language compilers or parsers:
```bash
python -m py_compile file.py          # Python
node --check file.js                  # JavaScript
tsc --noEmit file.ts                  # TypeScript
g++ -fsyntax-only file.cpp            # C/C++
```

---

## Deliverables

1. **Reconstructed Source File(s)**: Named after visible tabs or file titles.
2. **Uncertainty Report (`report.md` / `uncertain.json`)**: Exact lines with alternative readings and timestamps.
3. **Verification Status**: Clarifies what compiled cleanly vs what was inferred.

---

## Limitations

- **Severely Compressed Videos**: Text below 720p or heavily artifacted video can cause character confusion (`1/l/I`, `0/O`). Review the uncertainty report.
- **Multiple File Rewrites**: If the video author deletes and rewrites major sections, process each iteration as a separate time segment.
- **Blank Lines**: Dense consolidation may compress consecutive blank lines.

---

## Troubleshooting

| Issue | Likely Cause | Solution |
|---|---|---|
| `TesseractNotFoundError` | Tesseract binary not in system PATH | Install Tesseract or use the built-in EasyOCR fallback (`--engine easyocr`). |
| Low OCR confidence or missing symbols | Editor region too small or blurry | Increase `--scale 3` and use a tighter `--crop x,y,w,h` around code text. |
| Scrambled indentation | Gutter or line numbers included in crop | Adjust crop `x` coordinate to exclude line-number margins. |
