# tests/test_dsp.py
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
import librosa

from punkito_tabs_oracle.dsp.pitch import PitchTracker


def test_pitchtracker_on_sine():
    """Generar una señal senoidal pura a 110 Hz y verificar estimación <1% error."""
    sr = 22050
    duration = 1.0
    f = 110.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    y = 0.5 * np.sin(2 * np.pi * f * t)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        path = Path(tf.name)
    # Guardar usando soundfile
    sf.write(str(path), y, sr)

    tracker = PitchTracker(sr=sr, frame_length=2048, hop_length=512)
    f0 = tracker.estimar_f0(path)

    # Ignorar ceros y NaNs
    nonzero = f0[(f0 > 0.0) & (~np.isnan(f0))]
    assert nonzero.size > 0, "No se estimaron valores de f0"
    median_f0 = float(np.median(nonzero))
    rel_error = abs(median_f0 - f) / f
    assert rel_error < 0.01, f"Error relativo demasiado alto: {rel_error:.4f}"


def test_pitchtracker_beat_quantization():
    """Generar una sinusoide a 220 Hz (A3) y verificar obtener_f0_por_pulso."""
    sr = 22050
    duration = 2.0  # 2 segundos para múltiples beats
    f = 220.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    y = 0.5 * np.sin(2 * np.pi * f * t)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        path = Path(tf.name)
    sf.write(str(path), y, sr)

    tracker = PitchTracker(sr=sr)
    f0_pulsos, bpm = tracker.obtener_f0_por_pulso(path)

    # Verificar que obtuvimos pulsos y BPM
    assert len(f0_pulsos) > 0, "No se obtuvieron f0 pulsos"
    assert bpm > 0, "BPM debe ser positivo"
    # La mayoría de pulsos deben ser voiceados (cercanos a 220 Hz)
    voiced_pulsos = np.array([f0_val for f0_val, _ in f0_pulsos if f0_val > 0.0])
    assert len(voiced_pulsos) > len(f0_pulsos) * 0.5, "Menos del 50% de pulsos voiceados"
    # Error de mediana en los pulsos voiceados
    median_pulso = float(np.median(voiced_pulsos))
    rel_error = abs(median_pulso - f) / f
    assert rel_error < 0.05, f"Error relativo en pulsos: {rel_error:.4f}"


def test_pitchtracker_interpolates_low_confidence_without_yin(monkeypatch):
    sr = 22050
    fake_audio = np.zeros(sr, dtype=float)
    yin_calls = {"count": 0}

    def fake_load(_path, sr, mono):
        return fake_audio, sr

    def fake_pyin(_y, fmin, fmax, sr, frame_length, hop_length):
        f0 = np.array([110.0, np.nan, np.nan, 110.0], dtype=float)
        voiced_flag = np.array([True, False, False, True], dtype=bool)
        voiced_prob = np.array([0.9, 0.01, 0.01, 0.95], dtype=float)
        return f0, voiced_flag, voiced_prob

    def fake_rms(y, frame_length, hop_length):
        return np.ones((1, 4), dtype=float)

    def fake_yin(*args, **kwargs):
        yin_calls["count"] += 1
        raise AssertionError("YIN no debe ejecutarse")

    monkeypatch.setattr(librosa, "load", fake_load)
    monkeypatch.setattr(librosa, "pyin", fake_pyin)
    monkeypatch.setattr(librosa.feature, "rms", fake_rms)
    monkeypatch.setattr(librosa, "yin", fake_yin)

    tracker = PitchTracker(
        sr=sr,
        frame_length=2048,
        hop_length=512,
        voiced_confidence_threshold=0.5,
        rms_silence_threshold=0.0,
    )
    f0 = tracker.estimar_f0(Path("dummy.wav"))

    assert yin_calls["count"] == 0
    assert np.allclose(f0, np.array([110.0, 110.0, 110.0, 110.0], dtype=float), atol=1e-3)


def test_detect_legato_handles_nan_gaps_with_interpolation():
    tracker = PitchTracker(sr=22050)
    f0 = np.array([110.0, 111.0, 0.0, 0.0, 120.0, 121.0], dtype=float)
    voiced_prob = np.ones_like(f0, dtype=float)
    onsets = np.array([], dtype=int)

    legato_mask = tracker._detect_legato(f0=f0, voiced_prob=voiced_prob, onsets=onsets)

    assert legato_mask.dtype == bool
    assert legato_mask[1]
    assert legato_mask[5]


def test_obtener_f0_por_pulso_integrates_detect_slides(monkeypatch):
    tracker = PitchTracker(sr=22050)
    f0_raw = np.array([110.0, 111.0, 112.0, 113.0], dtype=float)
    fake_y = np.zeros(1024, dtype=float)

    monkeypatch.setattr(librosa, "load", lambda _p, sr, mono: (fake_y, sr))
    monkeypatch.setattr(tracker, "estimar_f0", lambda _p: f0_raw)
    monkeypatch.setattr(librosa.beat, "tempo", lambda y, sr: np.array([120.0], dtype=float))
    monkeypatch.setattr(
        librosa.beat,
        "beat_track",
        lambda y, sr: (120.0, np.array([0, 2], dtype=int)),
    )
    monkeypatch.setattr(
        tracker,
        "_extract_beat_windows",
        lambda y, beat_frames, f0: [(0, 2), (2, 4)],
    )
    monkeypatch.setattr(
        librosa,
        "pyin",
        lambda *args, **kwargs: (
            np.array([110.0, 111.0, 112.0, 113.0], dtype=float),
            np.ones(4, dtype=bool),
            np.ones(4, dtype=float),
        ),
    )
    monkeypatch.setattr(
        librosa.onset, "onset_detect", lambda **kwargs: np.array([], dtype=int)
    )
    monkeypatch.setattr(
        tracker, "_detect_ghost_notes", lambda y, f0, voiced_prob, beat_frames: np.zeros(4, dtype=bool)
    )
    monkeypatch.setattr(
        tracker, "_detect_legato", lambda f0, voiced_prob, onsets: np.zeros(4, dtype=bool)
    )
    monkeypatch.setattr(
        tracker, "detect_slides", lambda **kwargs: [(1, 3, 45, 47)]
    )

    f0_pulsos, _ = tracker.obtener_f0_por_pulso(Path("dummy.wav"))

    assert [art for _, art in f0_pulsos] == ["legato", "legato"]