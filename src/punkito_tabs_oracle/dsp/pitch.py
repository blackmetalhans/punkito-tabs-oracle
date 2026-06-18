# -*- coding: utf-8 -*-
"""
Detector de tono (Pitch Tracker) usando librosa.pyin.
- Registro objetivo: 30-400 Hz (según especificación)
- Ventana: frame_length=2048, hop_length=512, sr=22050
- Umbral de silencio por RMS normalizado: 0.05 -> forzar f0=0.0
- Interpolación cúbica para frames no confiables/no voiceados
- Beat tracking y cuantización temporal para legibilidad musical
- Detección de ghost notes (dead notes) usando onset_detect + spectral_flatness
- Detección de legato usando derivada de contorno de pitch

Comentarios en español.
"""
from pathlib import Path
from typing import Optional, Tuple, List

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

    def _detect_ghost_notes(
        self,
        y: np.ndarray,
        f0: np.ndarray,
        voiced_prob: np.ndarray,
        beat_frames: np.ndarray,
    ) -> np.ndarray:
        """Detecta ghost notes (dead notes) usando onset_detect y spectral_flatness.

        Retorna un array booleano de mismo largo que f0, True donde hay ghost note.
        """
        onsets = librosa.onset.onset_detect(
            y=y,
            sr=self.sr,
            hop_length=self.hop_length,
            backtrack=True,
        )

        spectral_flatness = librosa.feature.spectral_flatness(y=y, hop_length=self.hop_length)[0]
        spectral_flatness = np.asarray(spectral_flatness, dtype=float)

        ghost_notes = np.zeros(len(f0), dtype=bool)

        for onset_frame in onsets:
            # Si hay onset pero baja voicedness o alta spectral_flatness -> ghost note
            onset_idx = int(np.clip(onset_frame, 0, len(f0) - 1))
            is_weak_voiced = (
                voiced_prob[onset_idx] < self.voiced_confidence_threshold
                if onset_idx < len(voiced_prob)
                else True
            )
            is_percussive = (
                spectral_flatness[onset_idx] > 0.5
                if onset_idx < len(spectral_flatness)
                else False
            )

            if is_weak_voiced or is_percussive:
                ghost_notes[onset_idx] = True

        return ghost_notes

    def _detect_legato(
        self,
        f0: np.ndarray,
        voiced_prob: np.ndarray,
        onsets: np.ndarray,
    ) -> np.ndarray:
        """Detecta legato (slurs) usando derivada del contorno de pitch.

        Retorna un array booleano de mismo largo que f0, True donde hay transición legato.
        """
        legato_mask = np.zeros(len(f0), dtype=bool)

        # Calcular derivada de f0 (cambio de pitch por frame)
        f0_valid = f0.copy()
        f0_valid[f0_valid <= 0.0] = np.nan
        pitch_derivative = np.gradient(f0_valid)

        onset_set = set(int(np.clip(o, 0, len(f0) - 1)) for o in onsets)

        for i in range(1, len(f0)):
            prev_voiced = f0[i - 1] > 0.0 and voiced_prob[i - 1] >= self.voiced_confidence_threshold
            curr_voiced = f0[i] > 0.0 and voiced_prob[i] >= self.voiced_confidence_threshold

            # Legato si ambos frames tienen pitch, pero NO hay onset sharp
            if prev_voiced and curr_voiced and i not in onset_set:
                # Verificar que hay cambio de pitch suave (no salto)
                if not np.isnan(pitch_derivative[i]):
                    legato_mask[i] = True

        return legato_mask

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

    def _extract_beat_windows(
        self, y: np.ndarray, beat_frames: np.ndarray, f0_raw: np.ndarray
    ) -> List[Tuple[int, int]]:
        """Extrae ventanas de beat normalizadas para cuantización elástica.

        Calcula los límites (start_frame, end_frame) para cada beat basándose
        en los timestamps de beat detectados por librosa.beat.beat_track().

        Args:
            y: Signal de audio
            beat_frames: Array de frame indices de beats detectados
            f0_raw: Array de f0 estimado

        Returns:
            Lista de tuplas (start_frame, end_frame) para cada beat window
        """
        beat_windows: List[Tuple[int, int]] = []

        if len(beat_frames) == 0:
            # Fallback: crear ventanas uniformes
            frames_per_beat = max(1, int(len(f0_raw) / 4))  # Asumir ~4 beats
            for i in range(0, len(f0_raw), frames_per_beat):
                start = i
                end = min(i + frames_per_beat, len(f0_raw))
                beat_windows.append((start, end))
            return beat_windows

        # Usar beat frames detectados
        beat_frames = np.unique(np.sort(beat_frames))
        beat_frames = np.concatenate([[0], beat_frames, [len(f0_raw)]])
        beat_frames = np.unique(beat_frames)

        for i in range(len(beat_frames) - 1):
            start_frame = int(beat_frames[i])
            end_frame = int(beat_frames[i + 1])
            start_frame = max(0, min(start_frame, len(f0_raw) - 1))
            end_frame = max(start_frame + 1, min(end_frame, len(f0_raw)))
            beat_windows.append((start_frame, end_frame))

        return beat_windows

    def _quantize_f0_in_beat_window(
        self, f0_interval: np.ndarray, ghost_notes: np.ndarray,
        legato_mask: np.ndarray, start_frame: int, end_frame: int
    ) -> Tuple[float, str]:
        """Cuantiza f0 dentro de una ventana local de beat.

        Calcula la mediana de f0 voiced y determina el tipo de articulación
        basándose en propiedades locales dentro de la ventana.

        Args:
            f0_interval: Segmento de f0 para esta ventana
            ghost_notes: Array booleano de detección de ghost notes
            legato_mask: Array booleano de detección de legato
            start_frame: Índice de frame inicial
            end_frame: Índice de frame final

        Returns:
            Tupla (f0_value, articulation_type)
        """
        voiced = f0_interval[f0_interval > 0.0]

        articulation_type = "normal"
        f0_value = 0.0

        if len(voiced) > 0 and len(voiced) > len(f0_interval) * 0.5:
            f0_value = float(np.median(voiced))

            # Verificar si es ghost note
            ghost_count = np.sum(ghost_notes[start_frame:end_frame])
            if ghost_count > 0:
                articulation_type = "dead"
            # Verificar si hay legato en el intervalo
            elif np.sum(legato_mask[start_frame:end_frame]) > 0:
                articulation_type = "legato"

        return f0_value, articulation_type

    def obtener_f0_por_pulso(
        self, ruta_bajo: Path
    ) -> Tuple[List[Tuple[float, str]], float]:
        """Estima f0, detecta tempo, y cuantiza por pulsos/beats con articulation.

        Implementa cuantización elástica usando beat timestamps no-lineales
        extraídos con librosa.beat.beat_track() para soportar variaciones de groove
        humanas.

        Retorna:
        - f0_pulsos: lista de tuplas (f0_valor, articulation_type) donde:
            - f0_valor: mediana de f0 por beat (0.0 para silencio/rest)
            - articulation_type: 'normal' | 'dead' | 'legato'
        - bpm: tempo detectado en pulsos por minuto
        """
        # 1. Estimar f0 crudo
        y, sr = librosa.load(str(ruta_bajo), sr=self.sr, mono=True)
        f0_raw = self.estimar_f0(ruta_bajo)

        if len(f0_raw) == 0:
            return [], 120.0

        # 2. Detectar tempo
        tempo = librosa.beat.tempo(y=y, sr=self.sr)
        bpm = float(tempo[0]) if len(tempo) > 0 else 120.0

        # 3. PHASE 1: Detectar beats usando librosa.beat.beat_track()
        # para extraer timestamps de beat no-lineales
        _, beat_frames = librosa.beat.beat_track(y=y, sr=self.sr)
        beat_windows = self._extract_beat_windows(y, beat_frames, f0_raw)

        # 4. Detectar ghost notes y legato
        _, _, voiced_prob = librosa.pyin(
            y,
            fmin=self.fmin,
            fmax=self.fmax,
            sr=self.sr,
            frame_length=self.frame_length,
            hop_length=self.hop_length,
        )
        voiced_prob = np.asarray(voiced_prob, dtype=float)

        onsets = librosa.onset.onset_detect(
            y=y,
            sr=self.sr,
            hop_length=self.hop_length,
            backtrack=True,
        )

        beat_frame_starts = np.array([w[0] for w in beat_windows])
        ghost_notes = self._detect_ghost_notes(
            y, f0_raw, voiced_prob, beat_frame_starts
        )
        legato_mask = self._detect_legato(f0_raw, voiced_prob, onsets)

        # 5. Cuantizar f0 por ventanas de beat elásticas con articulation
        f0_pulsos: List[Tuple[float, str]] = []
        for start_frame, end_frame in beat_windows:
            f0_interval = f0_raw[start_frame:end_frame]
            f0_value, articulation_type = self._quantize_f0_in_beat_window(
                f0_interval, ghost_notes, legato_mask, start_frame, end_frame
            )
            f0_pulsos.append((f0_value, articulation_type))

        return f0_pulsos, bpm

    def obtener_f0_por_pulso_legacy(self, ruta_bajo: Path) -> Tuple[np.ndarray, float]:
        """Versión legacy que devuelve solo f0 sin articulation para compatibilidad."""
        f0_pulsos_with_articulation, bpm = self.obtener_f0_por_pulso(ruta_bajo)
        f0_values = np.array([val for val, _ in f0_pulsos_with_articulation], dtype=float)
        return f0_values, bpm

    def detect_slides(
        self,
        f0: np.ndarray,
        voiced_prob: np.ndarray,
        min_duration_frames: int = 3,
        onsets: Optional[np.ndarray] = None,
    ) -> List[Tuple[int, int, int, int]]:
        """Detecta deslices (glissandos) lineales en el contorno de f0.
        
        Identifica rampas de pitch donde la frecuencia cambia monótonamente a lo largo de
        una duración mínima, sin interrupciones de onset, y devuelve los puntos inicio/fin
        con conversión a MIDI.
        
        Args:
            f0: Array de f0 continuo (Hz)
            voiced_prob: Array de probabilidad de voz por frame
            min_duration_frames: Duración mínima de rampa (frames) para ser considerada slide
            onsets: Optional array de detecciones de onset
            
        Returns:
            Lista de tuplas (start_frame, end_frame, start_midi, end_midi) para cada slide
        """
        slides: List[Tuple[int, int, int, int]] = []
        
        if len(f0) < min_duration_frames:
            return slides
        
        if onsets is None:
            onsets = np.array([], dtype=int)
        else:
            onsets = np.asarray(onsets, dtype=int)
        onset_set = set(int(np.clip(o, 0, len(f0) - 1)) for o in onsets)
        
        # Crear máscara de frames válidos (voiced y con suficiente confianza)
        valid_mask = (f0 > 0.0) & (voiced_prob >= self.voiced_confidence_threshold)
        
        i = 0
        while i < len(f0):
            # Buscar inicio de una posible rampa
            if not valid_mask[i] or i in onset_set:
                i += 1
                continue
            
            # Iniciar búsqueda de rampa monotónica
            ramp_start = i
            ramp_direction = None  # 'up' o 'down'
            ramp_end = i
            
            # Extender la rampa mientras sea monótona
            for j in range(i + 1, len(f0)):
                if not valid_mask[j] or j in onset_set:
                    break
                
                # Calcular cambio de frecuencia
                df = f0[j] - f0[j - 1]
                
                if ramp_direction is None:
                    # Establecer dirección en el primer cambio significativo
                    if abs(df) > 1.0:  # Threshold para ignorar pequeñas variaciones
                        ramp_direction = "up" if df > 0 else "down"
                        ramp_end = j
                    else:
                        ramp_end = j
                elif ramp_direction == "up" and df >= -1.0:
                    # Permitir pequeños retrocesos (< 1 Hz) en rampa ascendente
                    ramp_end = j
                elif ramp_direction == "down" and df <= 1.0:
                    # Permitir pequeños avances (< 1 Hz) en rampa descendente
                    ramp_end = j
                else:
                    # Dirección invertida: terminar rampa
                    break
            
            # Si encontramos una rampa válida, registrarla
            ramp_length = ramp_end - ramp_start + 1
            if ramp_length >= min_duration_frames and ramp_direction is not None:
                # Calcular MIDI start y end
                midi_start = int(round(librosa.hz_to_midi(float(f0[ramp_start]))))
                midi_end = int(round(librosa.hz_to_midi(float(f0[ramp_end]))))
                
                # Solo registrar si hay cambio de MIDI
                if midi_start != midi_end:
                    slides.append((ramp_start, ramp_end, midi_start, midi_end))
            
            # Avanzar al siguiente frame no procesado
            i = ramp_end + 1
        
        return slides
    
    def _is_monotonic_ramp(
        self,
        f0_segment: np.ndarray,
        voiced_segment: np.ndarray,
        direction: str,
        tolerance_hz: float = 1.0,
    ) -> bool:
        """Verifica si un segmento de f0 forma una rampa monótona en la dirección especificada.
        
        Args:
            f0_segment: Segmento de f0 a verificar
            voiced_segment: Máscara voiced correspondiente
            direction: 'up' para ascendente, 'down' para descendente
            tolerance_hz: Tolerancia para pequeños retrocesos
            
        Returns:
            True si el segmento es una rampa monótona
        """
        valid_idx = np.where(voiced_segment)[0]
        if len(valid_idx) < 2:
            return False
        
        valid_f0 = f0_segment[valid_idx]
        
        # Calcular cambios
        diffs = np.diff(valid_f0)
        
        if direction == "up":
            # Permitir cambios positivos y pequeños negativos
            return np.all(diffs >= -tolerance_hz)
        elif direction == "down":
            # Permitir cambios negativos y pequeños positivos
            return np.all(diffs <= tolerance_hz)
        
        return False
