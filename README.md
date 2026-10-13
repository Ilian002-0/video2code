# video2code

An agent skill that reconstructs the source code shown on screen in a video (a tutorial, a screencast, a conference talk) as real files, with a report of every line it is not sure about.

It is built on the approach described in "Extracting Code from Programming Tutorial Videos" (ACE, Onward! 2016). Code in a video is typed and scrolled live, so no single frame contains the whole file, and OCR on compressed video is noisy. The skill addresses both problems rather than reading one screenshot and hoping for the best.

## How it differs from general video analysis

| | General video analysis | video2code |
|---|---|---|
| Goal | Summarize a video or describe its content | Reconstruct the code that appears in it |
| Frame sampling | Sparse, evenly spaced frames | Dense frames (1 to 2 per second) on the segments that show code only |
| Scrolling and live typing | Code that has scrolled out of view or is half typed is lost | Frames are aligned onto one growing document, so each line is recovered from the frames where it is visible |
| Handling OCR errors | A single reading per line | Many readings per line, combined by a confidence-weighted vote |
| Indentation | Often flattened | Rebuilt from the position of each word on screen |
| Verification | None | Token, line and fragment checks, the last one by the language's own parser or compiler |
| Uncertainty | Not reported | Each doubtful line is listed with its timestamp and alternative readings |
| Output | Prose, a timeline or notes | Source files, plus an uncertainty report |

## How it works

1. **Look for the source first.** The video description and chapters are checked for a repository or a link to the code. If one exists, it is more reliable than OCR.
2. **Locate the code.** The transcript and sparse frames identify the time ranges where an editor or terminal is on screen. The rest of the video is ignored.
3. **Crop and sample.** The editor pane is isolated and dense frames are extracted for each range.
4. **OCR with geometry.** `scripts/ocr_frames.py` reads each frame, skips near-identical ones, and rebuilds indentation from word positions.
5. **Consolidate.** `scripts/consolidate.py` aligns the lines of every frame onto a single document and keeps, for each line, the reading best supported by all its observations.
6. **Correct at three levels.** Identifiers are checked against the project vocabulary and the transcript, then each line for balanced brackets and quotes, then the whole file by `py_compile`, `node --check`, `tsc --noEmit` or an equivalent.
7. **Report.** Lines that remain ambiguous are flagged instead of guessed.

The model only chooses among readings that were actually observed and never completes or rewrites code that was not on screen.

## Installation

### Via skills CLI (recommended)

```bash
npx skills add Ilian002-0/video2code
```

### Manual installation

The skill uses the standard `SKILL.md` format and works with agents that support it.

| Agent | Project scope | Global scope |
|---|---|---|
| Antigravity | `<project>/.agents/skills/video2code/` | `~/.gemini/config/skills/video2code/` |
| Claude Code | `<project>/.claude/skills/video2code/` | `~/.claude/skills/video2code/` |

```bash
git clone https://github.com/Ilian002-0/video2code.git
cp -r video2code <one of the directories above>
```

### Dependencies

```bash
# macOS
brew install yt-dlp ffmpeg tesseract
# Debian / Ubuntu
sudo apt install yt-dlp ffmpeg tesseract-ocr
# Windows
winget install yt-dlp Gyan.FFmpeg UB-Mannheim.TesseractOCR

pip install pytesseract pillow
```

## Usage

Ask your agent, for example:

> Extract the code from this video: https://www.youtube.com/watch?v=...
> Extract the Python function shown in `demo.mp4` between 02:10 and 03:40 and check that it compiles.

The scripts can also be run on their own:

```bash
# 1. Dense frames for the segment that shows code
ffmpeg -ss 00:02:10 -to 00:03:40 -i demo.mp4 -vf "fps=2" frames/f_%05d.png

# 2. OCR (x,y,w,h is the editor pane)
python scripts/ocr_frames.py frames/ --out ocr/ --fps 2 --t0 130 --crop 270,110,1000,570 --scale 2

# 3. Consolidation
python scripts/consolidate.py ocr/ --out code.txt --report uncertain.json
```

A quick self-test that needs no video is available: `python tests/make_synthetic_test.py`.

## Output

- The extracted source file or files, named after the tabs or file names visible in the video when possible.
- A report listing, for each uncertain line, the chosen reading, the alternatives, and the video timestamp where it can be checked.
- The verification result (parsed or compiled, or not checked for lack of a compiler).

A file that compiles is not guaranteed to be identical to the original, which is why the report matters.

## Limitations

- It has been tested on synthetic frames. Real compressed video will be noisier, and thresholds such as `--min-sim`, `--scale` and `--fps` may need tuning.
- Blank lines are not preserved, and similar glyphs (`l`, `1`, `I`, `O`, `0`) can still be confused. Check the uncertainty report.
- If the author rewrites large parts of a file, treat each version as a separate segment.

## License

MIT. See [LICENSE](LICENSE).
