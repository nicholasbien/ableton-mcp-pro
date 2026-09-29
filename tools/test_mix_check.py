"""
Tests for mix_check with synthetic audio where the right answer is known (no Live, no files):

    python tools/test_mix_check.py
"""

import os
import sys
import tempfile

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(__file__))
import mix_check as mc

SR = 44100
t = np.arange(SR * 40) / SR
rng = np.random.default_rng(0)


def stereo(mono):
    return np.stack([mono, mono], axis=1)


def test_sub_sine_is_sub_and_mono():
    m = mc.measure(stereo(0.5 * np.sin(2 * np.pi * 45 * t)), SR)
    assert max(m["bands_db"], key=m["bands_db"].get) == "sub", m
    assert m["bands_db"]["sub"] > -1.0, m
    assert m["low_mono_corr"] > 0.99, m
    assert m["clipped_samples"] == 0 and m["peak_dbfs"] < -5.9, m


def test_wide_noise_is_not_mono():
    x = rng.normal(0, 0.1, (len(t), 2))
    m = mc.measure(x, SR)
    assert m["low_mono_corr"] < 0.2, m
    assert "not mono" in " ".join(mc.compare(m, [m]))


def test_clipping_and_true_peak_flagged():
    x = stereo(np.clip(1.5 * np.sin(2 * np.pi * 997 * t), -1, 1))
    m = mc.measure(x, SR)
    assert m["clipped_samples"] > 0, m
    assert any("over:" in g for g in mc.compare(m, [m])), mc.compare(m, [m])


def test_loudest_window_finds_the_drop():
    quiet, loud = 0.05 * np.sin(2 * np.pi * 100 * t[:SR * 20]), 0.8 * np.sin(2 * np.pi * 100 * t[:SR * 30])
    x = stereo(np.concatenate([quiet, loud, quiet]))
    w = mc.loudest_window(x, SR)
    assert len(w) == 30 * SR and np.abs(w).max() > 0.7 and np.abs(w).mean() > 0.4


def test_compare_flags_a_dark_mix():
    bright = stereo(0.3 * np.sin(2 * np.pi * 50 * t) + 0.1 * rng.normal(0, 1, len(t)))
    dark = stereo(0.3 * np.sin(2 * np.pi * 50 * t) + 0.01 * rng.normal(0, 1, len(t)))
    gaps = mc.compare(mc.measure(dark, SR), [mc.measure(bright, SR)])
    assert any(g.startswith("presence -") for g in gaps) and any(g.startswith("air -") for g in gaps), gaps


def test_cli_with_reference_and_sections():
    with tempfile.TemporaryDirectory() as d:
        a, b = os.path.join(d, "mix.wav"), os.path.join(d, "ref.wav")
        sf.write(a, stereo(0.4 * np.sin(2 * np.pi * 45 * t)), SR)
        sf.write(b, stereo(0.4 * np.sin(2 * np.pi * 45 * t) + 0.05 * rng.normal(0, 1, len(t))), SR)
        mc.main([a, "--ref", b, "--bpm", "120", "--sections", "8,8"])


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
