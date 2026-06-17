# tests/test_dsp.py
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

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
    voiced_pulsos = f0_pulsos[f0_pulsos > 0]
    assert len(voiced_pulsos) > len(f0_pulsos) * 0.5, "Menos del 50% de pulsos voiceados"
    # Error de mediana en los pulsos voiceados
    median_pulso = float(np.median(voiced_pulsos))
    rel_error = abs(median_pulso - f) / f
    assert rel_error < 0.05, f"Error relativo en pulsos: {rel_error:.4f}"