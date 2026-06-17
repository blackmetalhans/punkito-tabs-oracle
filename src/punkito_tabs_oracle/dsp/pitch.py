# -*- coding: utf-8 -*-
"""
Detector de tono (Pitch Tracker) usando librosa.pyin.
- Registro objetivo: 30-400 Hz (según especificación)
- Ventana: frame_length=2048, hop_length=512, sr=22050
- Umbral de silencio por RMS normalizado: 0.05 -> forzar f0=0.0

Comentarios en español.
"""
from pathlib import Path
from typing import Optional

import numpy as np
import librosa


class PitchTracker:
    """Estimador de f0 mediante pYIN con supresión por RMS.

    Parámetros opcionales para facilitar pruebas y reutilización.
    """

    def __init__(self, sr: int = 22050, frame_length: int = 2048, hop_length: int = 512, fmin: float = 30.0, fmax: float = 400.0):
        self.sr = sr
        self.frame_length = frame_length
        self.hop_length = hop_length
        self.fmin = fmin
        self.fmax = fmax

    def estimar_f0(self, audio_path: Path) -> np.ndarray:
        """Carga el archivo WAV y estima f0 por frame en Hz.

        - Retorna un array numpy 1D con f0 por frame.
        - Un valor de 0.0 indica silencio / no-voz.
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
        f0[np.isnan(f0)] = 0.0

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
            mask_silence = rms_norm[:n_frames] < 0.05
            f0[:n_frames][mask_silence] = 0.0

        return f0
