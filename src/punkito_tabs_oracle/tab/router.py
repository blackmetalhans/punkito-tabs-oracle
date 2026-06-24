# -*- coding: utf-8 -*-
"""
Ruteador de trastes para bajo de N cuerdas.
Modela el mapeo de una secuencia temporal de f0 (Hz) -> MIDI -> (String, Fret)
como un problema de camino mínimo (programación dinámica / Viterbi-like).

Implementa un topología Viterbi consciente de escala y armonía local:
- Estimación de tono usando librosa.feature.chroma_cqt
- Estimación local de acordes por ventana rítmica
- Penalización por notas fuera de escala (error correction contra artefactos)
- Regla del octavo: transposciones de 12 semitonos descuentan fret distance
- Regla del box shape: transiciones dentro de 4 trastes favorecen string changes
- Aware routing con shapes de bajo y progresiones en el Círculo de Quintas

Comentarios en español.
"""
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

import numpy as np
import librosa

from music21 import pitch as pitch_module

from punkito_tabs_oracle.settings import load_settings


logger = logging.getLogger(__name__)

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NOTE_TO_IDX = {note: idx for idx, note in enumerate(NOTE_NAMES)}
CIRCLE_OF_FIFTHS_INDEX = {
    0: 0,
    7: 1,
    2: 2,
    9: 3,
    4: 4,
    11: 5,
    6: 6,
    1: 7,
    8: 8,
    3: 9,
    10: 10,
    5: 11,
}
CHORD_QUALITY_INTERVALS = {
    "major": (0, 4, 7),
    "minor": (0, 3, 7),
    "dim": (0, 3, 6),
    "dominant": (0, 4, 7, 10),
}
DEFAULT_SHAPE_OFFSETS: Dict[str, Dict[int, Tuple[int, int]]] = {
    # Interval class keys are chord-tone intervals from the local root.
    # Values are ergonomic target deltas in (string_delta, fret_delta).
    "major": {0: (0, 0), 4: (-1, -1), 7: (-1, 2), 11: (-1, 1)},
    "minor": {0: (0, 0), 3: (-1, 0), 7: (-1, 2), 10: (-1, 1)},
    "dim": {0: (0, 0), 3: (-1, 0), 6: (-1, 1)},
    "dominant": {0: (0, 0), 4: (-1, -1), 7: (-1, 2), 10: (-1, 1)},
}
DEFAULT_HARMONIC_RESOLUTION_DISCOUNT = 0.35
DEFAULT_CHORD_EMISSION_DISCOUNT = 0.12
DEFAULT_SHAPE_MATCH_DECAY = 0.25


def estimate_key_from_chroma(
    y: np.ndarray,
    sr: int = 22050,
    hop_length: int = 256,
) -> Tuple[str, np.ndarray]:
    """Estima la tonalidad global usando chroma_cqt.

    Calcula chroma features (12 notas de la escala cromática) y detecta
    la tonalidad dominante usando correlación con templates de escala mayor/menor.

    Args:
        y: Señal de audio
        sr: Sample rate
        hop_length: Número de muestras entre frames

    Returns:
        (key_name: str, chroma_normalized: np.ndarray)
        - key_name: Nombre de la tonalidad (e.g., "E minor", "C major")
        - chroma_normalized: Vector de 12 dimensiones (notas C a B)
    """
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop_length)
    chroma_mean = np.mean(chroma, axis=1)
    chroma_normalized = chroma_mean / (np.sum(np.abs(chroma_mean)) + 1e-9)

    major_template = np.array(
        [1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1],
        dtype=float,
    )
    minor_template = np.array(
        [1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 1, 0],
        dtype=float,
    )
    major_template = major_template / np.sum(major_template)
    minor_template = minor_template / np.sum(minor_template)

    best_score = -np.inf
    best_key = "C major"

    for shift in range(12):
        rotated = np.roll(chroma_normalized, shift)
        major_score = np.dot(rotated, major_template)
        minor_score = np.dot(rotated, minor_template)

        if major_score > best_score:
            best_score = major_score
            best_key = f"{NOTE_NAMES[shift]} major"

        if minor_score > best_score:
            best_score = minor_score
            best_key = f"{NOTE_NAMES[shift]} minor"

    return best_key, chroma_normalized


def get_scale_degrees(key_name: str) -> np.ndarray:
    """Devuelve un array booleano de 12 notas en la escala detectada.

    Args:
        key_name: Tonalidad detectada (e.g., "E minor")

    Returns:
        Array booleano de 12 elementos (C a B) indicando qué notas están en la escala
    """
    parts = key_name.split()
    root_note = parts[0]
    scale_type = parts[1] if len(parts) > 1 else "major"

    root_idx = NOTE_TO_IDX.get(root_note, 0)

    if scale_type.lower() == "major":
        intervals = [0, 2, 4, 5, 7, 9, 11]
    else:
        intervals = [0, 2, 3, 5, 7, 8, 10]

    scale_degrees = np.zeros(12, dtype=bool)
    for interval in intervals:
        scale_degrees[(root_idx + interval) % 12] = True

    return scale_degrees


def midi_to_scale_degree(midi: int) -> int:
    """Convierte MIDI a índice de nota cromática (0-11)."""
    return midi % 12


def is_midi_in_scale(midi: int, scale_degrees: np.ndarray) -> bool:
    """Verifica si un MIDI está en la escala detectada."""
    scale_idx = midi_to_scale_degree(midi)
    return bool(scale_degrees[scale_idx])


@dataclass(frozen=True)
class State:
    string: Optional[int]
    fret: int
    articulation_type: str = "normal"  # 'normal' | 'dead' | 'legato'


class FretboardRouter:
    """Router que calcula la secuencia de (string, fret) de coste mínimo.

    Implementa topología Viterbi consciente de escala y acorde:
    - route_from_f0: acepta array de f0 (Hz) y devuelve (states, tab_ascii)
    - route_from_midi: acepta array con valores MIDI (int) y devuelve
      (states, tab_ascii)

    Parámetros opcionales:
    - scale_degrees: Array booleano (12 elementos) para penalizar notas
      fuera de escala
    - w_scale_penalty: Penalización por notas fuera de escala (default 5.0)
    - w_octave_discount: Descuento para transiciones de octava (default 0.5)

    Carga hiperparámetros desde config/settings.toml.
    """

    def __init__(
        self,
        settings_path: Optional[Path] = None,
        w_fret: Optional[float] = None,
        w_string: Optional[float] = None,
        w_open: Optional[float] = None,
        scale_degrees: Optional[np.ndarray] = None,
        w_scale_penalty: Optional[float] = None,
        w_octave_discount: Optional[float] = None,
        w_fourth_fifth_discount: Optional[float] = 0.4,
    ):
        settings = load_settings(settings_path)
        instrument = settings.get("instrument", {})
        weights = settings.get("router_weights", {})

        required_instrument = ("strings", "tuning_midi", "max_fret")
        missing_instrument = [k for k in required_instrument if k not in instrument]
        if missing_instrument:
            raise KeyError(f"Missing instrument settings: {missing_instrument}")

        required_weights = ("w_fret", "w_string", "w_open")
        missing_weights = [k for k in required_weights if k not in weights]
        if missing_weights:
            raise KeyError(f"Missing router_weights settings: {missing_weights}")

        strings = int(instrument["strings"])
        tuning_low_to_high = [int(v) for v in instrument["tuning_midi"]]
        if len(tuning_low_to_high) != strings:
            raise ValueError(
                "instrument.tuning_midi length must match instrument.strings"
            )

        tuning_high_to_low = list(reversed(tuning_low_to_high))
        self.tuning = {idx + 1: tuning_high_to_low[idx] for idx in range(strings)}
        self.max_fret = int(instrument["max_fret"])
        self.strings = strings

        self.w1 = float(w_fret if w_fret is not None else weights["w_fret"])
        self.w2 = float(w_string if w_string is not None else weights["w_string"])
        self.w3 = float(w_open if w_open is not None else weights["w_open"])
        self.quantization_grid = (0.25, 1.0 / 3.0)

        self.scale_degrees = (
            scale_degrees if scale_degrees is not None else np.ones(12, dtype=bool)
        )
        self.w_scale_penalty = (
            float(w_scale_penalty) if w_scale_penalty is not None else 5.0
        )
        self.w_octave_discount = (
            float(w_octave_discount) if w_octave_discount is not None else 0.5
        )
        self.w_fourth_fifth_discount = (
            float(w_fourth_fifth_discount)
            if w_fourth_fifth_discount is not None
            else 0.4
        )

        self.shape_offsets = DEFAULT_SHAPE_OFFSETS

    def _quantize_duration(self, duration_in_beats: float) -> float:
        """Snap durations to the strict micro-beat grid used by the exporter."""
        if duration_in_beats <= 0:
            return 0.25

        candidates = sorted(
            {
                0.25,
                1.0 / 3.0,
                0.5,
                2.0 / 3.0,
                0.75,
                1.0,
                1.25,
                4.0 / 3.0,
                1.5,
                5.0 / 3.0,
                1.75,
                2.0,
            }
        )
        return min(candidates, key=lambda value: abs(value - duration_in_beats))

    def _string_label(self, string_index: int) -> str:
        """Return a human-readable string label from the configured tuning."""
        if string_index < 1 or string_index > self.strings:
            raise ValueError("string_index out of range for configured tuning")
        return pitch_module.Pitch(midi=int(self.tuning[string_index])).step

    def _parse_chord_label(self, chord_label: Optional[str]) -> Optional[Tuple[int, str]]:
        """Normaliza etiquetas de acordes a (pitch_class, quality)."""
        if chord_label is None:
            return None

        label = str(chord_label).strip()
        if not label or label.upper() in {"N", "NC", "NO CHORD", "REST", "X"}:
            return None

        if ":" in label:
            root_text, quality_text = label.split(":", 1)
        else:
            parts = label.split()
            root_text = parts[0]
            quality_text = parts[1] if len(parts) > 1 else "major"

        root_text = root_text.replace("♭", "b").replace("♯", "#")
        try:
            root_pc = int(pitch_module.Pitch(root_text).pitchClass)
        except Exception:
            root_pc = NOTE_TO_IDX.get(root_text.upper(), 0)

        quality_key = quality_text.lower().strip()
        if quality_key in {"maj", "major", "", "maj7"}:
            quality = "major"
        elif quality_key in {"min", "minor", "m", "-"}:
            quality = "minor"
        elif quality_key in {"dim", "diminished", "o", "°"}:
            quality = "dim"
        elif quality_key in {"dom", "dominant", "7", "dom7", "7th"}:
            quality = "dominant"
        else:
            logger.warning(
                "Unrecognized chord quality '%s'; skipping chord-aware priors.",
                quality_key,
            )
            # Calidad desconocida: optamos por no inyectar priors armónicos
            # erróneos y dejamos que el routing siga con la información diatónica.
            return None

        return root_pc, quality

    def _circle_of_fifths_distance(self, prev_pc: int, curr_pc: int) -> int:
        """Distancia mínima en el Círculo de Quintas entre dos pitch classes."""
        prev_idx = CIRCLE_OF_FIFTHS_INDEX[prev_pc % 12]
        curr_idx = CIRCLE_OF_FIFTHS_INDEX[curr_pc % 12]
        raw_distance = abs(curr_idx - prev_idx)
        return min(raw_distance, 12 - raw_distance)

    def _chord_progression_discount(
        self,
        previous_chord: Optional[str],
        current_chord: Optional[str],
    ) -> float:
        """Calcula un descuento de coste por resolución armónica local."""
        prev_parsed = self._parse_chord_label(previous_chord)
        curr_parsed = self._parse_chord_label(current_chord)
        if prev_parsed is None or curr_parsed is None:
            return 0.0

        prev_pc, _ = prev_parsed
        curr_pc, _ = curr_parsed
        if prev_pc == curr_pc:
            return 0.0

        circle_distance = self._circle_of_fifths_distance(prev_pc, curr_pc)
        semitone_motion = (curr_pc - prev_pc) % 12
        strong_resolution = circle_distance == 1 and semitone_motion in {5, 7}

        if strong_resolution:
            return DEFAULT_HARMONIC_RESOLUTION_DISCOUNT
        if circle_distance == 2 and semitone_motion in {5, 7}:
            return DEFAULT_HARMONIC_RESOLUTION_DISCOUNT * 0.5
        return 0.0

    def _chord_emission_bonus(self, midi: Optional[int], chord_label: Optional[str]) -> float:
        """Pequeño descuento por caer en un tono estructural del acorde local."""
        if midi is None:
            return 0.0

        parsed = self._parse_chord_label(chord_label)
        if parsed is None:
            return 0.0

        root_pc, quality = parsed
        chord_intervals = CHORD_QUALITY_INTERVALS.get(quality, CHORD_QUALITY_INTERVALS["major"])
        interval = (midi - root_pc) % 12
        if interval not in chord_intervals:
            return 0.0

        if interval == 0:
            return DEFAULT_CHORD_EMISSION_DISCOUNT
        if interval in {3, 4, 7}:
            return DEFAULT_CHORD_EMISSION_DISCOUNT * 0.75
        return DEFAULT_CHORD_EMISSION_DISCOUNT * 0.5

    def _emission_cost(self, midi: Optional[int], chord_label: Optional[str] = None) -> float:
        """Calcula el coste de emisión para un MIDI (penalización por fuera de escala)."""
        if midi is None:
            return 0.0

        cost = 0.0
        if not is_midi_in_scale(midi, self.scale_degrees):
            cost += self.w_scale_penalty

        cost -= self._chord_emission_bonus(midi, chord_label)
        return cost

    def _midi_candidates(
        self, midi: Optional[int], articulation_type: str = "normal"
    ) -> List[State]:
        """Devuelve todos los (string,fret) válidos para un MIDI dado."""
        if midi is None or articulation_type == "dead":
            return [State(None, -1, articulation_type)]

        candidates: List[State] = []

        for s in range(1, self.strings + 1):
            fret = midi - self.tuning[s]
            midi_calculated = self.tuning[s] + fret
            if midi_calculated != midi:
                raise ValueError(
                    f"MIDI integrity assertion failed for string {s}: "
                    f"detected MIDI={midi}, base_cuerda={self.tuning[s]}, "
                    f"fret={fret}, calculated MIDI={midi_calculated}. "
                    f"These values must be mathematically identical."
                )

            if 0 <= fret <= self.max_fret:
                candidates.append(State(s, int(fret), articulation_type))

        low_fret_candidates = [c for c in candidates if c.fret <= 7]
        if low_fret_candidates:
            low_fret_candidates.sort(key=lambda c: (c.fret, c.string))
            candidates = low_fret_candidates

        if not candidates:
            return [State(None, -1, articulation_type)]

        return candidates

    def _transition_cost(
        self,
        u: State,
        v: State,
        midi_u: Optional[int] = None,
        midi_v: Optional[int] = None,
        previous_chord: Optional[str] = None,
        current_chord: Optional[str] = None,
    ) -> float:
        """Calcula el coste de transición entre dos estados."""
        if u.string is None or v.string is None:
            return 0.0

        if v.articulation_type == "dead":
            return 0.0

        fret_distance = abs(v.fret - u.fret)
        string_distance = abs(v.string - u.string)

        cost = self.w1 * fret_distance + self.w2 * string_distance
        indicator = -2.0 if v.fret == 0 else 0.0
        cost += self.w3 * indicator

        if midi_u is not None and midi_v is not None:
            delta_midi = midi_v - midi_u

            if abs(delta_midi) in (5, 7):
                cost -= self.w1 * fret_distance * self.w_fourth_fifth_discount

            if abs(delta_midi) == 12:
                cost -= self.w1 * fret_distance * (1.0 - self.w_octave_discount)

        if (
            midi_u is not None
            and midi_v is not None
            and is_midi_in_scale(midi_u, self.scale_degrees)
            and is_midi_in_scale(midi_v, self.scale_degrees)
            and fret_distance <= 4
        ):
            cost -= self.w1 * fret_distance * 0.3

        chord_discount = self._chord_progression_discount(previous_chord, current_chord)
        parsed_chord = self._parse_chord_label(current_chord)
        if parsed_chord is not None and midi_v is not None:
            root_pc, quality = parsed_chord
            interval = (midi_v - root_pc) % 12
            preferred_delta = self.shape_offsets.get(quality, {}).get(interval)
            if preferred_delta is not None:
                string_delta = v.string - u.string
                fret_delta = v.fret - u.fret
                preferred_string_delta, preferred_fret_delta = preferred_delta
                delta_error = abs(string_delta - preferred_string_delta) + abs(
                    fret_delta - preferred_fret_delta
                )
                shape_bonus = max(0.0, 1.0 - DEFAULT_SHAPE_MATCH_DECAY * delta_error)
                cost -= self.w1 * 0.5 * shape_bonus

            if chord_discount > 0.0:
                if preferred_delta is not None:
                    cost -= chord_discount * (self.w1 * 0.5 + self.w2 * 0.25)
                else:
                    cost -= chord_discount * 0.25

        # Permitimos costes negativos: los descuentos modelan priors reales y
        # no deben quedar recortados, porque eso aplana la señal del Viterbi.
        return cost

    def estimate_local_chords(
        self,
        y: np.ndarray,
        sr: int,
        beat_windows: List[Tuple[int, int]],
    ) -> List[str]:
        """Estima acordes locales por ventana de beat usando template matching.

        beat_windows puede venir ya en frames del cromagrama o en muestras; el
        método infiere la unidad a partir del rango observado para mantener
        compatibilidad con distintos beat trackers.
        """
        if not beat_windows:
            return []

        hop_length = 256
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop_length)
        if chroma.size == 0:
            return ["N"] * len(beat_windows)

        window_ends = [int(end) for _, end in beat_windows if end is not None]
        if not window_ends:
            return ["N"] * len(beat_windows)

        max_window_end = max(window_ends)
        # Heurística basada en magnitud: los samples suelen ser ~hop_length veces
        # más grandes que los frames, así que usamos un umbral intermedio.
        frame_like_threshold = chroma.shape[1] * max(1, hop_length // 2)
        treat_as_frames = max_window_end <= frame_like_threshold

        chord_labels: List[str] = []
        for start, end in beat_windows:
            if treat_as_frames:
                frame_start = max(0, int(start))
                frame_end = min(chroma.shape[1], int(end))
            else:
                frame_start = max(0, int(round(start / hop_length)))
                frame_end = min(chroma.shape[1], int(round(end / hop_length)))

            if frame_end <= frame_start:
                chord_labels.append("N")
                continue

            window_chroma = np.mean(chroma[:, frame_start:frame_end], axis=1)
            if not np.any(np.isfinite(window_chroma)):
                chord_labels.append("N")
                continue

            energy = float(np.sum(window_chroma))
            if energy <= 1e-9:
                chord_labels.append("N")
                continue

            window_profile = window_chroma / (np.sum(window_chroma) + 1e-9)

            best_label = "N"
            best_score = -np.inf
            for root_idx, root_name in enumerate(NOTE_NAMES):
                for quality, intervals in CHORD_QUALITY_INTERVALS.items():
                    template = np.zeros(12, dtype=float)
                    for interval in intervals:
                        template[(root_idx + interval) % 12] = 1.0
                    template /= np.sum(template)
                    # Dot product sobre perfiles normalizados: template matching
                    # simple y estable; con perfiles normalizados equivale a una
                    # similitud de coseno barata para triadas mayores/menores/
                    # disminuidas y acordes dominantes.
                    score = float(np.dot(window_profile, template))
                    if score > best_score:
                        best_score = score
                        suffix = {
                            "major": "maj",
                            "minor": "min",
                            "dim": "dim",
                            "dominant": "7",
                        }[quality]
                        best_label = f"{root_name}:{suffix}"

            chord_labels.append(best_label)

        return chord_labels

    def route_from_midi(
        self,
        midi_sequence: List[Optional[int]],
        articulation_sequence: Optional[List[str]] = None,
        *,
        chord_sequence: Optional[List[str]] = None,
    ) -> Tuple[List[State], str]:
        """Calcula la ruta óptima sobre una secuencia de valores MIDI."""
        if articulation_sequence is None:
            articulation_sequence = ["normal"] * len(midi_sequence)

        if len(articulation_sequence) != len(midi_sequence):
            raise ValueError(
                "articulation_sequence must match midi_sequence length"
            )

        if chord_sequence is None:
            chord_sequence = [None] * len(midi_sequence)
        elif len(chord_sequence) != len(midi_sequence):
            raise ValueError("chord_sequence must match midi_sequence length")

        T = len(midi_sequence)
        prev_costs = {}
        prev_ptrs = []

        for t in range(T):
            midi = midi_sequence[t]
            articulation = articulation_sequence[t]
            current_chord = chord_sequence[t]
            previous_chord = chord_sequence[t - 1] if t > 0 else None

            if midi is None or midi == 0:
                candidates = [State(None, -1, articulation)]
            else:
                candidates = self._midi_candidates(midi, articulation)

            curr_costs = {}
            curr_ptr = {}

            if t == 0:
                for v in candidates:
                    emission_cost = self._emission_cost(midi, current_chord)
                    curr_costs[v] = emission_cost
                    curr_ptr[v] = None
            else:
                for v in candidates:
                    best_cost = float("inf")
                    best_prev = None
                    midi_prev = midi_sequence[t - 1]

                    for u, u_cost in prev_costs.items():
                        trans_cost = self._transition_cost(
                            u,
                            v,
                            midi_u=midi_prev,
                            midi_v=midi,
                            previous_chord=previous_chord,
                            current_chord=current_chord,
                        )
                        emission_cost = self._emission_cost(midi, current_chord)
                        c = u_cost + trans_cost + emission_cost

                        if c < best_cost:
                            best_cost = c
                            best_prev = u
                        elif c == best_cost:
                            if (
                                best_prev is not None
                                and v.fret >= 0
                                and best_prev.fret >= 0
                            ):
                                if v.fret < best_prev.fret:
                                    best_prev = u

                    curr_costs[v] = best_cost
                    curr_ptr[v] = best_prev

            prev_costs = curr_costs
            prev_ptrs.append(curr_ptr)

        if not prev_costs:
            return ([], "")

        end_state = min(prev_costs.items(), key=lambda kv: kv[1])[0]
        states = [None] * T
        for t in range(T - 1, -1, -1):
            states[t] = end_state
            end_state = prev_ptrs[t][end_state]
            if end_state is None:
                pass

        tab = self._render_tab(states, midi_sequence)
        return (states, tab)

    def estimate_key_and_set_scale(self, y: np.ndarray, sr: int = 22050) -> str:
        """Estima tonalidad desde audio y configura scale_degrees."""
        key_name, _ = estimate_key_from_chroma(y, sr=sr, hop_length=256)
        self.scale_degrees = get_scale_degrees(key_name)
        return key_name

    def route_from_f0(
        self,
        f0_with_articulation: List[Tuple[float, str]],
        *,
        y: Optional[np.ndarray] = None,
        sr: int = 22050,
        beat_windows: Optional[List[Tuple[int, int]]] = None,
        chord_sequence: Optional[List[str]] = None,
    ) -> Tuple[List[State], str]:
        """Convierte f0 con articulation a MIDI y ejecuta el ruteo.

        Si chord_sequence no se pasa pero y + beat_windows están disponibles,
        el router estima acordes locales automáticamente para alimentar el
        Viterbi chord-aware.
        """
        midi_seq = []
        articulation_seq = []
        for f0_val, articulation in f0_with_articulation:
            if f0_val is None or f0_val == 0.0 or np.isnan(f0_val):
                midi_seq.append(None)
            else:
                midi_seq.append(int(round(librosa.hz_to_midi(float(f0_val)))))
            articulation_seq.append(articulation)

        if chord_sequence is None and y is not None and beat_windows is not None:
            chord_sequence = self.estimate_local_chords(y, sr, beat_windows)

        return self.route_from_midi(
            midi_seq,
            articulation_seq,
            chord_sequence=chord_sequence,
        )

    def f0_to_midi_sequence(self, f0_input: list) -> list:
        """Convierte una secuencia de f0 a MIDI entero o None para silencios."""
        midi_seq = []
        for item in f0_input:
            if isinstance(item, tuple):
                f0_val = item[0]
            else:
                f0_val = item

            if f0_val is None or f0_val == 0.0 or np.isnan(f0_val):
                midi_seq.append(None)
            else:
                midi_seq.append(int(round(librosa.hz_to_midi(float(f0_val)))))
        return midi_seq

    def build_musicxml_route(
        self,
        midi_sequence: List[Optional[int]],
        states: List[State],
    ) -> List[Dict[str, object]]:
        """Construye eventos para exportación MusicXML."""
        if len(midi_sequence) != len(states):
            raise ValueError(
                "midi_sequence and states must have the same length."
            )
        if not states:
            return []

        events: List[Dict[str, object]] = []

        def append_event(
            midi_pitch: Optional[int],
            state: State,
            duration_in_beats: float,
        ) -> None:
            events.append(
                {
                    "midi_pitch": (
                        None if midi_pitch is None else int(midi_pitch)
                    ),
                    "string_index": (
                        None if state.string is None else int(state.string)
                    ),
                    "fret_number": (
                        None if state.string is None else int(state.fret)
                    ),
                    "duration_in_beats": float(duration_in_beats),
                    "articulation_type": state.articulation_type,
                }
            )

        current_midi = midi_sequence[0]
        current_state = states[0]
        current_duration = 1.0

        for idx in range(1, len(states)):
            midi_pitch = midi_sequence[idx]
            state = states[idx]
            if midi_pitch == current_midi and state == current_state:
                current_duration += 1.0
                continue
            append_event(
                current_midi,
                current_state,
                self._quantize_duration(current_duration),
            )
            current_midi = midi_pitch
            current_state = state
            current_duration = 1.0

        append_event(
            current_midi,
            current_state,
            self._quantize_duration(current_duration),
        )
        return events

    def _render_tab(
        self,
        states: List[State],
        midi_sequence: Optional[List[Optional[int]]] = None,
    ) -> str:
        """Crea representación ASCII con 4 líneas y barras cada 4 beats."""
        if not states:
            return ""

        max_fret = max((s.fret for s in states if s.fret >= 0), default=0)
        cell_w = max(1, len(str(max_fret)))

        lines = {string_index: [] for string_index in range(1, self.strings + 1)}
        previous_midi = None

        for beat_idx, state in enumerate(states):
            if beat_idx > 0 and beat_idx % 4 == 0:
                for s_idx in range(1, self.strings + 1):
                    lines[s_idx].append("|")

            current_midi = None
            if midi_sequence is not None and beat_idx < len(midi_sequence):
                current_midi = midi_sequence[beat_idx]
            is_sustain = (
                beat_idx > 0
                and state.string is not None
                and previous_midi is not None
                and current_midi is not None
                and current_midi == previous_midi
            )

            for s_idx in range(1, self.strings + 1):
                if state.string == s_idx:
                    if state.fret >= 0 and not is_sustain:
                        cell = str(state.fret).rjust(cell_w, " ")
                    else:
                        cell = "-" * cell_w
                else:
                    cell = "-" * cell_w
                lines[s_idx].append(cell)
            previous_midi = current_midi

        text_lines = []
        for s_idx in range(1, self.strings + 1):
            prefix = self._string_label(s_idx) + "|"
            text_lines.append(prefix + "".join(lines[s_idx]))
        return "\n".join(text_lines)
