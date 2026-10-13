#!/usr/bin/env python3
"""Consolidate noisy per-frame OCR into one document (ACE-style).

Usage: consolidate.py OCR_DIR --out code.txt [--report uncertain.json] [--min-sim 0.6]

1. Align each frame's lines onto the growing document (DP alignment, fuzzy line
   similarity; scrolling = cheap doc-line skips, typing = frame-line inserts).
2. Per document line, keep every observation (text, conf, time).
3. Choose the final text: weighted medoid (confidence x recency), then per-character
   vote among candidates of the same length.
4. Lines with a single observation or low agreement go to the report.
"""
import argparse, json, os, sys
from collections import Counter
from difflib import SequenceMatcher

SKIP, INS = -0.05, -0.4


def sim(a, b):
    if not a.strip() and not b.strip():
        return 1.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def align(doc, frame, min_sim):
    n, m = len(doc), len(frame)
    S = [[0.0] * (m + 1) for _ in range(n + 1)]
    B = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        S[i][0], B[i][0] = 0.0, "skip"  # leading doc lines not visible: free
    for j in range(1, m + 1):
        S[0][j], B[0][j] = S[0][j - 1] + INS, "ins"
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            s = sim(doc[i - 1]["best"], frame[j - 1]["text"])
            cand = [(S[i - 1][j] + SKIP, "skip"), (S[i][j - 1] + INS, "ins")]
            if s >= min_sim:
                cand.append((S[i - 1][j - 1] + (s - min_sim + 0.1), "match"))
            S[i][j], B[i][j] = max(cand)
    # trailing doc lines not visible: free -> best end cell in last column
    i = max(range(n + 1), key=lambda k: S[k][m])
    j = m
    ops = []
    while j > 0 or i > 0:
        if i == 0:
            ops.append(("ins", None, j - 1)); j -= 1; continue
        if j == 0:
            break
        op = B[i][j]
        if op == "match":
            ops.append(("match", i - 1, j - 1)); i -= 1; j -= 1
        elif op == "skip":
            i -= 1
        else:
            ops.append(("ins", i, j - 1)); j -= 1  # insert after doc line i-1
    return ops[::-1]


def best_text(obs, t_max):
    cands = {}
    for o in obs:
        cands.setdefault(o["text"], 0.0)
    scored = []
    for c in cands:
        sc = 0.0
        for o in obs:
            rec = 1.0 + 0.5 * (o["t"] / t_max if t_max else 0)  # later = more likely final
            sc += o["conf"] * rec * sim(c, o["text"])
        scored.append((sc, c))
    scored.sort(reverse=True)
    top = scored[0][1]
    # per-character vote among same-length observations
    same = [o for o in obs if len(o["text"]) == len(top)]
    if len(same) >= 3:
        out = []
        for k in range(len(top)):
            cnt = Counter()
            for o in same:
                cnt[o["text"][k]] += o["conf"]
            out.append(cnt.most_common(1)[0][0])
        voted = "".join(out)
        if sim(voted, top) > 0.9:
            top = voted
    agree = sum(sim(top, o["text"]) for o in obs) / len(obs)
    return top, agree, [c for _, c in scored[:4]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ocr_dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--report")
    ap.add_argument("--min-sim", type=float, default=0.6)
    a = ap.parse_args()
    frames = []
    for f in sorted(os.listdir(a.ocr_dir)):
        if f.endswith(".json"):
            frames.append(json.load(open(os.path.join(a.ocr_dir, f))))
    frames.sort(key=lambda x: x["t"])
    if not frames:
        sys.exit("no OCR frames found")
    t_max = frames[-1]["t"] or 1.0
    doc = []  # each: {"obs": [...], "best": str}

    def add(line, t):
        return {"obs": [{"text": line["text"], "conf": line["conf"], "t": t}], "best": line["text"]}

    for fr in frames:
        lines = [l for l in fr["lines"] if l["text"].strip()]
        if not doc:
            doc = [add(l, fr["t"]) for l in lines]
            continue
        ops = align(doc, lines, a.min_sim)
        pending = {}
        matched_doc = {}
        for kind, i, j in ops:
            if kind == "match":
                matched_doc[i] = j
            else:
                if i is not None:
                    pending.setdefault(i, []).append(j)
        # inserts "after doc line i-1" are stored under key i; i is None = before everything
        out = []
        head = [j for (k, i, j) in ops if k == "ins" and i is None]
        for j in head:
            out.append(add(lines[j], fr["t"]))
        for di, d in enumerate(doc):
            if di in matched_doc:
                d["obs"].append({"text": lines[matched_doc[di]]["text"], "conf": lines[matched_doc[di]]["conf"], "t": fr["t"]})
                d["best"] = best_text(d["obs"], t_max)[0]
            out.append(d)
            for j in pending.get(di + 1, []):
                out.append(add(lines[j], fr["t"]))
        doc = out

    final, report = [], []
    for k, d in enumerate(doc, 1):
        text, agree, cands = best_text(d["obs"], t_max)
        final.append(text)
        n = len(d["obs"])
        mean_conf = sum(o["conf"] for o in d["obs"]) / n
        if n == 1 or agree < 0.92 or mean_conf < 0.6:
            report.append({"line": k, "chosen": text, "observations": n, "agreement": round(agree, 3),
                           "mean_conf": round(mean_conf, 3), "candidates": cands,
                           "first_seen_t": d["obs"][0]["t"], "last_seen_t": d["obs"][-1]["t"]})
    open(a.out, "w").write("\n".join(final) + "\n")
    if a.report:
        json.dump(report, open(a.report, "w"), indent=2)
    print(f"{len(final)} lines, {len(report)} uncertain -> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
