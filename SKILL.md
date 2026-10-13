---
name: video2code
description: Extract source code (or on-screen docs/config/terminal text) shown in a video (YouTube, local file) as clean, verified files, not just a transcript. Use when the user wants the code from a coding tutorial, conference talk, screencast or IDE recording, or asks to "get the code from this video". Combines frame selection, OCR, multi-frame consolidation, and correction (token, line, fragment) following the ACE approach.
---

# video2code (Video Code Extractor)

Goal: turn a video where code is displayed on screen into **files that actually run**, with an explicit list of what is uncertain. Never rely on the transcript alone, and never rely on single-frame OCR alone.

## Why a single OCR pass is not enough (ACE approach, Onward! 2016)

The paper "Extracting Code from Programming Tutorial Videos" (tool: ACE) identifies two problems:

1. **Partial visibility.** Code is typed live and scrolls. No single frame contains the full file. The same line appears in dozens of frames, sometimes half-typed, sometimes hidden by a cursor, tooltip or autocomplete popup.
2. **OCR noise.** OCR on compressed video confuses `l/1/I`, `O/0`, `rn/m`, drops indentation, merges `==` or `->`, and mangles symbols.

ACE's answer, which this skill reproduces:

1. **Consolidate across frames.** Align every frame's lines onto one growing document. Each line then has many noisy observations. Take a weighted vote (per line, then per character) so random OCR errors cancel out and only systematic errors survive.
2. **Correct with a language model at three levels.** Token level (is this identifier/keyword plausible?), line level (does this line look like valid code in this language?), fragment level (does the whole block parse/compile?). ACE used statistical n-gram models; here the "language model" is a mix of: project vocabulary, an LLM pass restricted to the OCR candidates, and the real parser/compiler.

Rule that follows: **correct by choosing among observed candidates and verifying with a parser, never by "rewriting what the code should be".**

## Pipeline

Work in `WORK=./vce_work`. Prerequisites: `yt-dlp`, `ffmpeg`, `tesseract` + `pip install pytesseract pillow rapidfuzz` (easyocr is a valid replacement for tesseract). Scripts are in `scripts/` next to this file.

### 0. Cheap wins first
- `yt-dlp --dump-json --skip-download <url>`: read `description`, `chapters`. Look for GitHub/Gist/Drive links and "code available at...". If the source repo exists, **use it** and use the video only to locate the relevant commit/file. Stop here if that covers the need.

### 1. Get video + timestamped transcript
```bash
yt-dlp -f "bv*[height<=1080]+ba/b[height<=1080]" -o "$WORK/video.%(ext)s" <url>
yt-dlp --skip-download --write-auto-subs --sub-langs "en.*,fr.*" --convert-subs srt -o "$WORK/sub" <url>
```
Prefer 1080p: below 720p, OCR on code degrades sharply.

### 2. Locate the segments that show code (do not OCR the whole video)
Reuse existing tools for this step:
- **glideit** (`map_video`) gives a few storyboard images for a long video, then `zoom_video` for dense high-res frames of one window plus an OCR sidecar.
- or **mcp-video-analyzer** `analyze_video` (timeline + OCR) then `analyze_moment` on a time range.
- or sparse sampling: `ffmpeg -i video.mp4 -vf fps=1/10 "$WORK/map/m_%05d.png"` and read them (batches of 8-10) to find the time ranges where an editor/terminal/slide with code is visible.

Cross-check with the transcript ("now let's write the function...", "as you can see here"). Output: list of `(start, end, language, what)` segments.

### 3. Find the editor crop
Read one representative frame, locate the editor pane (exclude sidebar, line-number gutter if possible, terminal, webcam overlay). Note `x,y,w,h` in pixels. Cropping alone typically improves OCR more than any other step.

### 4. Extract dense frames per segment
```bash
ffmpeg -ss <start> -to <end> -i "$WORK/video.mp4" -vf "fps=2" "$WORK/frames/seg1/f_%05d.png"
```
`fps=2` for live typing, `fps=1` for static slides/scrolling. Timestamp of a frame = `start + index/fps`; the OCR script takes `--fps` and `--t0` for this.

### 5. OCR with geometry (keeps indentation)
```bash
python scripts/ocr_frames.py "$WORK/frames/seg1" --out "$WORK/ocr/seg1" \
    --fps 2 --t0 <start> --crop x,y,w,h --scale 2
```
Output: one JSON per *distinct* frame: `{"t": 12.5, "lines": [{"text": "    for i in range(n):", "conf": 0.91}]}`. Indentation is rebuilt from word x-positions. Dark themes are auto-inverted.

### 6. Consolidate across frames (the ACE core)
```bash
python scripts/consolidate.py "$WORK/ocr/seg1" --out "$WORK/code_seg1.txt" \
    --report "$WORK/uncertain_seg1.json"
```
What it does: aligns each frame to the growing document (semi-global dynamic programming alignment with fuzzy line similarity, so scrolling and typing are both handled), then picks, per line, the best candidate by confidence-weighted vote with a recency bonus (later = more likely final after edits), and does per-character voting among same-length candidates. Lines with disagreement, low confidence or a single observation go to the report with their top candidates.

Known limit: if the author rewrites large parts of the file, split into separate segments (one per "version") instead of one long segment.

### 7. Three-level correction

**7a. Token level (deterministic first).**
- Build a vocabulary: language keywords + identifiers that appear ≥2 times in the consolidated code + words from transcript/description (function and variable names are usually spoken).
- For tokens that appear once and are within edit distance 1-2 of a vocabulary identifier, fix them. Typical confusions: `l`↔`1`↔`I`, `O`↔`0`, `rn`↔`m`, `vv`↔`w`, `;`↔`:`, `,`↔`.`, `{`↔`(`, `'`↔`"`, dropped `_`.

**7b. Line level.** Check bracket/quote balance per line and across the block, trailing `:`/`;`/`{` consistent with the language, indentation in multiples of the file's unit, string/number literals plausible. For every uncertain line in the report, choose among the OCR candidates first; only propose a new form if no candidate is valid.

**7c. Fragment level (ground truth).** Run the real tool on the result, then loop (max 3 rounds) on the errors reported:
```bash
python -m py_compile file.py          # Python
node --check file.js                  # JS
npx tsc --noEmit file.ts              # TypeScript
g++ -fsyntax-only file.cpp            # C/C++ (missing includes may be expected)
```
If no compiler is available for the language, say so and fall back to 7a/7b only.

**LLM pass (after 7a, before/with 7c).** Give the model: consolidated code, the uncertain-lines report, the transcript excerpt for the same time range, and the vocabulary. Instructions:
- Pick among the observed candidates when one is valid.
- Fix only what the evidence supports (candidates, transcript, vocabulary, compiler error).
- Do not complete, refactor, rename or "improve" anything. Do not add code that was not on screen.
- Leave `# ??? <candidates>` on any line that stays ambiguous.

### 8. Deliverables
- The extracted file(s), named after the video's own filenames if visible (tab titles, terminal prompts).
- `report.md`: per file: source video + timestamp range, language, compile/parse status, list of uncertain lines (line number, chosen value, alternatives, frame time so the user can look at the image), anything that was visible only partially (autocomplete popup, cursor, off-screen lines).
- Say clearly what is **verified** (compiles/parses) vs **inferred**. Code that compiles is not necessarily identical to the video's code.

## Quality rules
- Prefer the repo/description over OCR whenever it exists.
- Never merge code from two different files/tabs: detect tab-title or file-name changes in the frames and segment on them.
- When the same code is shown twice (slide, then IDE), use both as independent observations.
- If OCR confidence is low across the board, re-extract with `--scale 3`, a tighter crop, or `fps=4`, before touching the text.
- Do not execute extracted code without telling the user; a syntax check is enough for verification.
