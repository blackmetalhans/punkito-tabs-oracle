# -*- coding: utf-8 -*-
"""
Detector de tono (Pitch Tracker) usando librosa.pyin.
- Registro objetivo: 30-400 Hz (según especificación)
- Ventana: frame_length=2048, hop_length=512, sr=22050
- Umbral de silencio por RMS normalizado: 0.05 -> forzar f0=0.0
- Interpolación cúbica para frames no confiables/no voiceados
- Beat tracking y cuantización temporal para legibilidad musical

Comentarios en español.
"""
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import scipy.signal

# Compatibilidad con SciPy>=1.9 para dependencias legacy en librosa.
if not hasattr(scipy.signal, "hann"):
    scipy.signal.hann = scipy.signal.windows.hann

import librosa
from scipy.interpolate import interp1d

from punkito_tabs_oracle.settings import load_settings


class PitchTracker:
    """Estimador de f0 mediante pYIN e interpolación de huecos.

    Parámetros opcionales para facilitar pruebas y reutilización.
    """

    def __init__(
        self,
        settings_path: Optional[Path] = None,
        sr: Optional[int] = None,
        frame_length: Optional[int] = None,
        hop_length: Optional[int] = None,
        fmin: Optional[float] = None,
        fmax: Optional[float] = None,
        voiced_confidence_threshold: Optional[float] = None,
        rms_silence_threshold: Optional[float] = None,
    ):
        settings = load_settings(settings_path)
        dsp = settings.get("dsp", {})
        required = (
            "sample_rate",
            "frame_length",
            "hop_length",
            "fmin",
            "fmax",
            "voiced_confidence_threshold",
            "rms_silence_threshold",
        )
        missing = [k for k in required if k not in dsp]
        if missing:
            raise KeyError(f"Missing dsp settings: {missing}")

        self.sr = int(sr if sr is not None else dsp["sample_rate"])
        self.frame_length = int(frame_length if frame_length is not None else dsp["frame_length"])
        self.hop_length = int(hop_length if hop_length is not None else dsp["hop_length"])
        self.fmin = float(fmin if fmin is not None else dsp["fmin"])
        self.fmax = float(fmax if fmax is not None else dsp["fmax"])
        self.voiced_confidence_threshold = float(
            voiced_confidence_threshold
            if voiced_confidence_threshold is not None
            else dsp["voiced_confidence_threshold"]
        )
        self.rms_silence_threshold = float(
            rms_silence_threshold
            if rms_silence_threshold is not None
            else dsp["rms_silence_threshold"]
        )
        self.quantization_grid = (0.25, 1.0 / 3.0)

    def quantize_duration(self, duration_in_beats: float) -> float:
        """Snap a duration to the strict micro-beat grid used by the exporter."""
        if duration_in_beats <= 0:
            return 0.25

        candidates = sorted(
            {0.25, 1.0 / 3.0, 0.5, 2.0 / 3.0, 0.75, 1.0, 1.25, 4.0 / 3.0, 1.5, 5.0 / 3.0, 1.75, 2.0}
        )
        return min(candidates, key=lambda value: abs(value - duration_in_beats))

    def _interpolate_low_confidence(self, f0: np.ndarray, valid_mask: np.ndarray) -> np.ndarray:
        """Interpola huecos internos de f0 usando interpolación cúbica."""
        if f0.size == 0:
            return f0

        interpolated = np.zeros_like(f0, dtype=float)
        valid_idx = np.flatnonzero(valid_mask)
        if valid_idx.size == 0:
            return interpolated

        interpolated[valid_idx] = f0[valid_idx]
        if valid_idx.size == 1:
            return interpolated

        interp_kind = "cubic" if valid_idx.size >= 4 else "linear"
        interpolator = interp1d(
            valid_idx.astype(float),
            f0[valid_idx].astype(float),
            kind=interp_kind,
            bounds_error=False,
            fill_value=np.nan,
        )

        span = np.arange(valid_idx[0], valid_idx[-1] + 1)
        span_values = np.asarray(interpolator(span), dtype=float)
        bridge_mask = ~valid_mask[span]
        span_out = interpolated[span]
        span_out[bridge_mask] = span_values[bridge_mask]
        interpolated[span] = span_out
        interpolated[np.isnan(interpolated)] = 0.0
        interpolated[interpolated < 0.0] = 0.0
        return interpolated

    def estimar_f0(self, audio_path: Path) -> np.ndarray:
        """Carga el archivo WAV y estima f0 por frame en Hz.

        - Retorna un array numpy 1D con f0 por frame.
        - Un valor de 0.0 indica silencio / no-voz.
        - Para frames de baja confianza/no voiceados usa interpolación cúbica.
        """
        # Cargar audio (mono)
        y, sr = librosa.load(str(audio_path), sr=self.sr, mono=True)

        # Ejecutar pYIN
        # librosa.pyin devuelve un array con NaNs donde no hay estimación
        f0, voiced_flag, voiced_prob = librosa.pyin(
            y,
            fmin=self.fmin,
            fmax=self.fmax,
            sr=self.sr,
            frame_length=self.frame_length,
            hop_length=self.hop_length,
        )

        # Garantizar vector numpy y reemplazar NaN por 0.0 (no-voz)
        f0 = np.asarray(f0, dtype=float)
        voiced_prob = np.asarray(voiced_prob, dtype=float)
        valid_mask = (~np.isnan(f0)) & (f0 > 0.0) & (voiced_prob >= self.voiced_confidence_threshold)
        f0 = self._interpolate_low_confidence(f0=f0, valid_mask=valid_mask)

        # Calcular RMS por frame con mismo frame/hop
        rms = librosa.feature.rms(y=y, frame_length=self.frame_length, hop_length=self.hop_length)[0]
        # Normalizar RMS al máximo (siempre proteger contra división por cero)
        max_rms = float(np.max(rms)) if rms.size > 0 else 0.0
        if max_rms > 0:
            rms_norm = rms / max_rms
        else:
            rms_norm = rms

        # Si RMS normalizado por frame cae por debajo del umbral, forzar f0=0.0
        # Alinear longitudes: librosa.pyin puede devolver más o menos frames, pero usando mismos frame/hop deben coincidir
        n_frames = min(len(f0), len(rms_norm))
        if n_frames > 0:
            mask_silence = rms_norm[:n_frames] < self.rms_silence_threshold
            f0[:n_frames][mask_silence] = 0.0

        return f0

    def obtener_f0_por_pulso(self, ruta_bajo: Path) -> Tuple[np.ndarray, float]:
        """Estima f0, detecta tempo, y cuantiza por pulsos/beats.

        Retorna:
        - f0_pulsos: array con mediana de f0 por beat (0.0 para silencio/rest)
        - bpm: tempo detectado en pulsos por minuto
        """
        # 1. Estimar f0 crudo
        y, sr = librosa.load(str(ruta_bajo), sr=self.sr, mono=True)
        f0_raw = self.estimar_f0(ruta_bajo)

        if len(f0_raw) == 0:
            return np.array([], dtype=float), 120.0

        # 2. Detectar tempo
        tempo = librosa.beat.tempo(y=y, sr=self.sr)
        bpm = float(tempo[0]) if len(tempo) > 0 else 120.0

        # 3. Detectar beats o usar fallback
        _, beat_frames = librosa.beat.beat_track(y=y, sr=self.sr)
        if len(beat_frames) == 0:
            # Fallback: segmentar en N beats según BPM estimado
            frames_per_beat = int((self.sr / self.hop_length) * (60.0 / bpm))
            frames_per_beat = max(1, frames_per_beat)
            beat_frames = np.arange(0, len(f0_raw), frames_per_beat)
            if beat_frames[-1] < len(f0_raw):
                beat_frames = np.concatenate([beat_frames, [len(f0_raw)]])
        else:
            beat_frames = np.unique(np.concatenate([[0], beat_frames, [len(f0_raw)]]))

        # 4. Cuantizar f0 por intervalos de beat
        f0_pulsos = []
        for i in range(len(beat_frames) - 1):
            start_frame = int(beat_frames[i])
            end_frame = int(beat_frames[i + 1])
            # Asegurar límites válidos
            start_frame = max(0, min(start_frame, len(f0_raw) - 1))
            end_frame = max(start_frame + 1, min(end_frame, len(f0_raw)))

            # Extraer frames de f0 en este intervalo de beat
            f0_interval = f0_raw[start_frame:end_frame]
            # Contar voiceados
            voiced = f0_interval[f0_interval > 0]
            # Si > 50% son voiced, usar mediana; si no, rest (0.0)
            if len(voiced) > 0 and len(voiced) > len(f0_interval) * 0.5:
                f0_pulsos.append(float(np.median(voiced)))
            else:
                f0_pulsos.append(0.0)

        return np.array(f0_pulsos, dtype=float), bpm
