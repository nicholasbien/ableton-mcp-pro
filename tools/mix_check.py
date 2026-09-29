"""
Measure a bounced mix, and compare it with reference tracks, the way the mix-check skill uses it:

    python tools/mix_check.py BOUNCE.aif --ref "Daphni - Cherry.mp3" --ref other.wav
    python tools/mix_check.py BOUNCE.aif --bpm 136 --sections 16,16,8,32,8,32,16
    python tools/mix_check.py BOUNCE.aif --ref REF.mp3 --json

Reports integrated loudness (LUFS), sample and true peak, crest factor, clipped samples, energy in
six bands relative to the total (so balance compares across different loudness), and how mono the
low end is. With references it compares the loudest 30 s of each file (drop against drop) as well
as the whole files, and flags gaps over 3 dB. It measures; it can't tell you if the track is good.

Needs numpy, scipy, soundfile and pyloudnorm:  pip install "ableton-mcp-pro[analysis]"
"""

from __future__ import annotations

import argparse
import json
import sys

try:
    import numpy as np
    import pyloudnorm as pyln
    import soundfile as sf
    from scipy.signal import butter, resample_poly, sosfilt
except ImportError as e:
    sys.exit(f"mix_check needs numpy, scipy, soundfile and pyloudnorm ({e}); "
             'install them with: pip install "ableton-mcp-pro[analysis]"')

BANDS = [("sub", 30, 60), ("bass", 60, 120), ("lowmid", 120, 400),
         ("mid", 400, 2000), ("presence", 2000, 6000), ("air", 6000, None)]
WINDOW = 30.0          # seconds compared as "the drop"
FLAG_DB = 3.0          # band / loudness gaps worth acting on


def db(v: float) -> float:
    return 20 * np.log10(max(float(v), 1e-12))


def load(path: str) -> tuple[np.ndarray, int]:
    x, sr = sf.read(path, always_2d=True)
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    return x[:, :2], sr


def _filter(sig, sr, lo, hi):
    if lo and hi:
        sos = butter(4, [lo, hi], btype="band", fs=sr, output="sos")
    elif hi:
        sos = butter(4, hi, btype="low", fs=sr, output="sos")
    else:
        sos = butter(4, lo, btype="high", fs=sr, output="sos")
    return sosfilt(sos, sig, axis=0)


def measure(x: np.ndarray, sr: int) -> dict:
    lufs = pyln.Meter(sr).integrated_loudness(x) if len(x) > sr * 0.5 else float("nan")
    rms = np.sqrt(np.mean(x ** 2))
    peak = np.abs(x).max()
    true_peak = np.abs(resample_poly(x, 4, 1, axis=0)).max()      # 4x oversampled inter-sample peak
    mono = x.mean(axis=1)
    energy = {name: np.sqrt(np.mean(_filter(mono, sr, lo, hi) ** 2)) for name, lo, hi in BANDS}
    total = np.sqrt(sum(v ** 2 for v in energy.values()))
    low = _filter(x, sr, None, 150)
    left, right = low[:, 0], low[:, 1]
    corr = float(np.corrcoef(left, right)[0, 1]) if left.std() > 0 and right.std() > 0 else 1.0
    return {"lufs": round(float(lufs), 1), "peak_dbfs": round(db(peak), 1), "true_peak_dbfs": round(db(true_peak), 1),
            "crest_db": round(db(peak) - db(rms), 1), "clipped_samples": int(np.sum(np.abs(x) >= 0.999)),
            "bands_db": {k: round(db(v) - db(total), 1) for k, v in energy.items()},
            "low_mono_corr": round(corr, 2)}


def loudest_window(x: np.ndarray, sr: int, seconds: float = WINDOW) -> np.ndarray:
    """The loudest `seconds` of the file by RMS (1 s hops): the drop, for drop-vs-drop comparison."""
    n = int(seconds * sr)
    if len(x) <= n:
        return x
    per_second = (x[:len(x) // sr * sr] ** 2).mean(axis=1).reshape(-1, sr).sum(axis=1)
    k = int(seconds)
    windows = np.convolve(per_second, np.ones(k), mode="valid")       # energy of each k-second window
    best = int(np.argmax(windows))
    return x[best * sr:best * sr + n]


def sections(x: np.ndarray, sr: int, bpm: float, bars: list[int]) -> list[dict]:
    bar = 4 * 60 / bpm
    out, t = [], 0.0
    for b in bars:
        seg = x[int(t * sr):int((t + b * bar) * sr)]
        if len(seg):
            out.append({"bars": f"{int(t / bar) + 1}-{int(t / bar) + b}", **measure(seg, sr)})
        t += b * bar
    return out


def compare(mine: dict, refs: list[dict]) -> list[str]:
    """Gaps between the mix and the average of the references, worst first."""
    notes = []
    avg = lambda key: float(np.mean([r[key] for r in refs]))
    d = mine["lufs"] - avg("lufs")
    if abs(d) >= FLAG_DB / 2:
        notes.append((abs(d), f"loudness {d:+.1f} LU vs refs ({mine['lufs']} vs {avg('lufs'):.1f} LUFS)"))
    for band in mine["bands_db"]:
        ref = float(np.mean([r["bands_db"][band] for r in refs]))
        d = mine["bands_db"][band] - ref
        if abs(d) >= FLAG_DB:
            notes.append((abs(d), f"{band} {d:+.1f} dB vs refs ({mine['bands_db'][band]} vs {ref:.1f})"))
    if mine["low_mono_corr"] < 0.9:
        notes.append((9, f"low end not mono enough: correlation {mine['low_mono_corr']} (< 0.9) - check stereo bass"))
    if mine["true_peak_dbfs"] > 0.0 or mine["clipped_samples"]:
        notes.append((9, f"over: true peak {mine['true_peak_dbfs']} dBTP, {mine['clipped_samples']} clipped samples"))
    return [text for _, text in sorted(notes, reverse=True)]


def row(label: str, m: dict) -> str:
    b = m["bands_db"]
    return (f"{label[:22]:<22} {m['lufs']:6.1f} {m['true_peak_dbfs']:6.1f} {m['crest_db']:5.1f} "
            + " ".join(f"{b[k]:7.1f}" for k, _, _ in BANDS) + f" {m['low_mono_corr']:5.2f}")


HEADER = (f"{'':<22} {'LUFS':>6} {'TP':>6} {'crest':>5} " + " ".join(f"{k:>7}" for k, _, _ in BANDS) + " mono")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Measure a mix and compare it with reference tracks.")
    ap.add_argument("mix")
    ap.add_argument("--ref", action="append", default=[], help="reference track (repeatable)")
    ap.add_argument("--bpm", type=float, help="with --sections: per-section breakdown")
    ap.add_argument("--sections", help="bar counts, e.g. 16,16,8,32,8,32,16")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    x, sr = load(args.mix)
    report = {"mix": args.mix, "seconds": round(len(x) / sr, 1), "whole": measure(x, sr),
              "drop": measure(loudest_window(x, sr), sr)}
    if args.bpm and args.sections:
        report["sections"] = sections(x, sr, args.bpm, [int(b) for b in args.sections.split(",")])
    refs = []
    for path in args.ref:
        rx, rsr = load(path)
        refs.append({"path": path, "whole": measure(rx, rsr), "drop": measure(loudest_window(rx, rsr), rsr)})
    if refs:
        report["refs"] = refs
        report["gaps_drop"] = compare(report["drop"], [r["drop"] for r in refs])
        report["gaps_whole"] = compare(report["whole"], [r["whole"] for r in refs])

    if args.json:
        print(json.dumps(report, indent=2))
        return
    print(f"{args.mix}  ({report['seconds']} s)\n\nbands are dB relative to the total; TP = true peak dBFS; "
          f"mono = low-end (<150 Hz) L/R correlation\n")
    print(HEADER)
    print(row("mix: whole", report["whole"]))
    print(row(f"mix: loudest {WINDOW:.0f} s", report["drop"]))
    for r in refs:
        name = r["path"].rsplit("/", 1)[-1].rsplit(".", 1)[0][:11]
        print(row(f"ref {name} whole", r["whole"]))
        print(row(f"ref {name} loud", r["drop"]))
    for s in report.get("sections", []):
        print(row(f"bars {s['bars']}", s))
    if refs:
        print("\ngaps, drop vs drop:" if report["gaps_drop"] else "\ndrop vs drop: within 3 dB of the references")
        for g in report["gaps_drop"]:
            print("  - " + g)


if __name__ == "__main__":
    main()
