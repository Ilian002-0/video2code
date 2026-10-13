#!/usr/bin/env python3
"""OCR a directory of video frames, keeping indentation and per-line confidence.

Usage:
  ocr_frames.py FRAMES_DIR --out OUT_DIR [--fps 2] [--t0 0] [--crop x,y,w,h]
                [--scale 2] [--lang eng] [--dedupe 3] [--engine auto|tesseract|easyocr]

Output: OUT_DIR/<frame>.json = {"t": seconds, "lines": [{"text", "conf"}]}
Near-identical consecutive frames (perceptual hash distance <= --dedupe) are skipped.
"""
import argparse, json, os, sys, warnings
warnings.filterwarnings('ignore')
from statistics import median
from PIL import Image, ImageOps

# Check common Windows install paths for tesseract
for _p in [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
]:
    if os.path.exists(_p):
        try:
            import pytesseract
            pytesseract.pytesseract.tesseract_cmd = _p
        except Exception:
            pass
        break


def ahash(img, n=16):
    g = img.convert("L").resize((n, n))
    px = list(g.getdata())
    m = sum(px) / len(px)
    return [1 if p > m else 0 for p in px]


def hdist(a, b):
    return sum(x != y for x, y in zip(a, b))


def prep(img, crop, scale):
    if crop:
        x, y, w, h = crop
        img = img.crop((x, y, x + w, y + h))
    img = img.convert("L")
    if sum(img.resize((32, 32)).getdata()) / 1024 < 110:  # dark theme -> invert
        img = ImageOps.invert(img)
    img = ImageOps.autocontrast(img)
    if scale != 1:
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    return img


def ocr_lines_tesseract(img, lang="eng"):
    import pytesseract
    d = pytesseract.image_to_data(img, lang=lang, config="--psm 6 -c preserve_interword_spaces=1",
                                  output_type=pytesseract.Output.DICT)
    rows = {}
    for i, txt in enumerate(d["text"]):
        if not txt.strip() or float(d["conf"][i]) < 0:
            continue
        key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        rows.setdefault(key, []).append((d["left"][i], d["width"][i], txt, float(d["conf"][i]) / 100))
    cw = [w / max(len(t), 1) for r in rows.values() for (_, w, t, _) in r if len(t) >= 3]
    char_w = median(cw) if cw else 10
    lines = []
    for key in sorted(rows, key=lambda k: min(x[0] for x in rows[k]) and k):
        words = sorted(rows[key])
        out, prev_right = "", None
        for left, width, txt, _ in words:
            if prev_right is None:
                out = " " * round(left / char_w)
            else:
                out += " " * max(1, round((left - prev_right) / char_w))
            out += txt
            prev_right = left + width
        conf = sum(c for *_, c in words) / len(words)
        lines.append({"text": out.rstrip(), "conf": round(conf, 3), "y": min(d["top"][i] for i in range(len(d["text"])) if d["line_num"][i] == key[2] and d["block_num"][i] == key[0] and d["par_num"][i] == key[1] and d["text"][i].strip())})
    lines.sort(key=lambda l: l["y"])
    for l in lines:
        l.pop("y")
    lead = [len(l["text"]) - len(l["text"].lstrip()) for l in lines if l["text"].strip()]
    m = min(lead) if lead else 0
    for l in lines:
        l["text"] = l["text"][m:]
    return lines


def ocr_lines_easyocr(img, reader):
    import numpy as np
    img_np = np.array(img)
    res = reader.readtext(img_np, paragraph=False)
    if not res:
        return []
    words = []
    for bbox, txt, conf in res:
        txt = txt.strip()
        if not txt:
            continue
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        left, top, right, bottom = float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))
        words.append({
            "left": left, "top": top, "right": right, "bottom": bottom,
            "width": right - left, "height": bottom - top, "text": txt, "conf": float(conf)
        })
    if not words:
        return []

    avg_h = median([w["height"] for w in words]) if words else 15
    line_groups = []
    for w in sorted(words, key=lambda x: (x["top"], x["left"])):
        placed = False
        for grp in line_groups:
            grp_y = median([(it["top"] + it["bottom"]) / 2 for it in grp])
            w_y = (w["top"] + w["bottom"]) / 2
            if abs(w_y - grp_y) <= avg_h * 0.55:
                grp.append(w)
                placed = True
                break
        if not placed:
            line_groups.append([w])

    cw = [w["width"] / max(len(w["text"]), 1) for w in words if len(w["text"]) >= 3]
    char_w = median(cw) if cw else (avg_h * 0.6)

    lines = []
    line_groups.sort(key=lambda grp: min(it["top"] for it in grp))
    for grp in line_groups:
        grp.sort(key=lambda it: it["left"])
        out, prev_right = "", None
        for it in grp:
            if prev_right is None:
                out = " " * round(it["left"] / char_w)
            else:
                out += " " * max(1, round((it["left"] - prev_right) / char_w))
            out += it["text"]
            prev_right = it["left"] + it["width"]
        conf = sum(it["conf"] for it in grp) / len(grp)
        lines.append({"text": out.rstrip(), "conf": round(conf, 3)})

    lead = [len(l["text"]) - len(l["text"].lstrip()) for l in lines if l["text"].strip()]
    m = min(lead) if lead else 0
    for l in lines:
        l["text"] = l["text"][m:]
    return lines


def choose_engine(requested="auto"):
    if requested in ("tesseract", "auto"):
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            return "tesseract"
        except Exception:
            if requested == "tesseract":
                raise
    if requested in ("easyocr", "auto"):
        try:
            import easyocr
            return "easyocr"
        except Exception:
            if requested == "easyocr":
                raise
    raise RuntimeError("Neither Tesseract nor EasyOCR is available.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames_dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--t0", type=float, default=0.0)
    ap.add_argument("--crop")
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--lang", default="eng")
    ap.add_argument("--dedupe", type=int, default=3)
    ap.add_argument("--engine", choices=["auto", "tesseract", "easyocr"], default="auto")
    a = ap.parse_args()

    engine = choose_engine(a.engine)
    easyocr_reader = None
    if engine == "easyocr":
        import easyocr
        lang_code = a.lang[:2] if len(a.lang) >= 2 else "en"
        easyocr_reader = easyocr.Reader([lang_code], gpu=False, verbose=False)

    crop = tuple(int(v) for v in a.crop.split(",")) if a.crop else None
    os.makedirs(a.out, exist_ok=True)
    files = sorted(f for f in os.listdir(a.frames_dir) if f.lower().endswith((".png", ".jpg", ".jpeg")))
    prev, kept = None, 0
    for idx, f in enumerate(files):
        img = Image.open(os.path.join(a.frames_dir, f))
        p = prep(img, crop, a.scale)
        h = ahash(p)
        if prev is not None and hdist(h, prev) <= a.dedupe:
            continue
        prev = h

        if engine == "tesseract":
            lines = ocr_lines_tesseract(p, lang=a.lang)
        else:
            lines = ocr_lines_easyocr(p, easyocr_reader)

        with open(os.path.join(a.out, os.path.splitext(f)[0] + ".json"), "w", encoding="utf-8") as fh:
            json.dump({"t": round(a.t0 + idx / a.fps, 2), "frame": f, "lines": lines}, fh, ensure_ascii=False)
        kept += 1
    print(f"{kept}/{len(files)} frames OCR'd ({engine}) -> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
