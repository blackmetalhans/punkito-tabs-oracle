# -*- coding: utf-8 -*-
"""
Ruteador de trastes para bajo de N cuerdas.
Modela el mapeo de una secuencia temporal de f0 (Hz) -> MIDI -> (String, Fret)
como un problema de camino mínimo (programación dinámica / Viterbi-like).

Comentarios en español.
"""
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

import numpy as np
import librosa

from music21 import pitch as pitch_module

from punkito_tabs_oracle.settings import load_settings


@dataclass(frozen=True)
class State:
    string: Optional[int]
    fret: int
    articulation_type: str = "normal"  # 'normal' | 'dead' | 'legato'


class FretboardRouter:
    """Router que calcula la secuencia de (string, fret) de coste mínimo.

    - route_from_f0: acepta array de f0 (Hz) y devuelve (states, tab_ascii)
    - route_from_midi: acepta array con valores MIDI (int) y devuelve (states, tab_ascii)

    Carga hiperparámetros desde config/settings.toml.
    """

    def __init__(
        self,
        settings_path: Optional[Path] = None,
        w_fret: Optional[float] = None,
        w_string: Optional[float] = None,
        w_open: Optional[float] = None,
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
            raise ValueError("instrument.tuning_midi length must match instrument.strings")

        # Internamente usamos 1=aguda ... 4=grave.
        tuning_high_to_low = list(reversed(tuning_low_to_high))
        self.tuning = {idx + 1: tuning_high_to_low[idx] for idx in range(strings)}
        self.max_fret = int(instrument["max_fret"])
        self.strings = strings

        self.w1 = float(w_fret if w_fret is not None else weights["w_fret"])
        self.w2 = float(w_string if w_string is not None else weights["w_string"])
        self.w3 = float(w_open if w_open is not None else weights["w_open"])
        self.quantization_grid = (0.25, 1.0 / 3.0)

    def _quantize_duration(self, duration_in_beats: float) -> float:
        """Snap durations to the strict micro-beat grid used by the exporter."""
        if duration_in_beats <= 0:
            return 0.25

        candidates = sorted(
            {0.25, 1.0 / 3.0, 0.5, 2.0 / 3.0, 0.75, 1.0, 1.25, 4.0 / 3.0, 1.5, 5.0 / 3.0, 1.75, 2.0}
        )
        return min(candidates, key=lambda value: abs(value - duration_in_beats))

    def _string_label(self, string_index: int) -> str:
        """Return a human-readable string label from the configured tuning."""
        if string_index < 1 or string_index > self.strings:
            raise ValueError("string_index out of range for configured tuning")
        return pitch_module.Pitch(midi=int(self.tuning[string_index])).step

    def _midi_candidates(
        self, midi: Optional[int], articulation_type: str = "normal"
    ) -> List[State]:
        """Devuelve todos los (string,fret) válidos para un MIDI dado.
        Si midi es None, devuelve sólo el estado de descanso.
        """
        if midi is None:
            return [State(None, -1, articulation_type)]
        candidates: List[State] = []
        for s in range(1, self.strings + 1):
            fret = midi - self.tuning[s]
            if 0 <= fret <= self.max_fret:
                candidates.append(State(s, int(fret), articulation_type))
        if not candidates:
            # No hay representación física -> rest
            return [State(None, -1)]
        return candidates

    def _transition_cost(self, u: State, v: State) -> float:
        # Si alguno es descanso, coste 0
        if u.string is None or v.string is None:
            return 0.0
        # Coste de movimiento horizontal y vertical
        cost = self.w1 * abs(v.fret - u.fret) + self.w2 * abs(v.string - u.string)
        # Recompensa por cuerda al aire: indicador devuelve -2.0 si fret==0
        indicator = -2.0 if v.fret == 0 else 0.0
        cost += self.w3 * indicator
        return cost

    def route_from_midi(
        self, midi_sequence: List[Optional[int]], articulation_sequence: Optional[List[str]] = None
    ) -> Tuple[List[State], str]:
        """Calcula la ruta óptima sobre una secuencia de valores MIDI (o None para silencio).

        Args:
            midi_sequence: List of MIDI pitches or None for rests
            articulation_sequence: Optional list of articulation types ('normal'|'dead'|'legato')

        Retorna (states, tab_ascii).
        """
        if articulation_sequence is None:
            articulation_sequence = ["normal"] * len(midi_sequence)

        if len(articulation_sequence) != len(midi_sequence):
            raise ValueError("articulation_sequence must match midi_sequence length")

        T = len(midi_sequence)
        prev_costs = {}
        prev_ptrs = []

        for t in range(T):
            midi = midi_sequence[t]
            articulation = articulation_sequence[t]

            if midi is None or midi == 0:
                candidates = [State(None, -1, articulation)]
            else:
                candidates = self._midi_candidates(midi, articulation)

            curr_costs = {}
            curr_ptr = {}

            if t == 0:
                for v in candidates:
                    curr_costs[v] = 0.0
                    curr_ptr[v] = None
            else:
                for v in candidates:
                    best_cost = float("inf")
                    best_prev = None
                    for u, u_cost in prev_costs.items():
                        c = u_cost + self._transition_cost(u, v)
                        if c < best_cost:
                            best_cost = c
                            best_prev = u
                        elif c == best_cost:
                            if best_prev is not None and v.fret >= 0 and best_prev.fret >= 0:
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

    def route_from_f0(
        self, f0_with_articulation: List[Tuple[float, str]]
    ) -> Tuple[List[State], str]:
        """Convierte f0 con articulation a MIDI y ejecuta el ruteo.

        Args:
            f0_with_articulation: List of tuples (f0_hz, articulation_type)

        f0==0.0 se considera silencio/rest (None)
        """
        midi_seq = []
        articulation_seq = []
        for f0_val, articulation in f0_with_articulation:
            if f0_val is None or f0_val == 0.0 or np.isnan(f0_val):
                midi_seq.append(None)
            else:
                midi_seq.append(int(round(librosa.hz_to_midi(float(f0_val)))))
            articulation_seq.append(articulation)

        return self.route_from_midi(midi_seq, articulation_seq)

    def f0_to_midi_sequence(
        self, f0_input: list
    ) -> list:
        """Convierte una secuencia de f0 a MIDI entero o None para silencios.

        Maneja tanto el formato legacy (floats) como el nuevo (tuples con articulation).
        """
        midi_seq = []
        for item in f0_input:
            # Handle both legacy (float) and new (tuple) formats
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
        """Construye eventos para exportación MusicXML con duración en beats y articulation.

        Agrupa beats consecutivos con mismo (midi, cuerda, traste, articulation) en un
        único evento para representar sustain.
        """
        if len(midi_sequence) != len(states):
            raise ValueError("midi_sequence and states must have the same length.")
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
                    "midi_pitch": None if midi_pitch is None else int(midi_pitch),
                    "string_index": None if state.string is None else int(state.string),
                    "fret_number": None if state.string is None else int(state.fret),
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
            if (midi_pitch == current_midi and state == current_state):
                current_duration += 1.0
                continue
            append_event(current_midi, current_state, self._quantize_duration(current_duration))
            current_midi = midi_pitch
            current_state = state
            current_duration = 1.0

        append_event(current_midi, current_state, self._quantize_duration(current_duration))
        return events

    def _render_tab(self, states: List[State], midi_sequence: Optional[List[Optional[int]]] = None) -> str:
        """Crea una representación ASCII clásica de 4 líneas con barras de compás cada 4 beats.

        - Cada carácter representa un pulso/beat (cuantizado).
        - Inserta barras '|' cada 4 beats para agrupar en compases 4/4.
        """
        if not states:
            return ""

        # Anchura de celda según dígitos de traste
        max_fret = max((s.fret for s in states if s.fret >= 0), default=0)
        cell_w = max(1, len(str(max_fret)))

        lines = {string_index: [] for string_index in range(1, self.strings + 1)}
        previous_midi = None

        for beat_idx, state in enumerate(states):
            # Cada beat_idx=0,1,2,3 forma un compás; cada beat_idx%4==0 = nueva barra
            if beat_idx > 0 and beat_idx % 4 == 0:
                # Insertar barra de compás
                for s_idx in range(1, 5):
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

            # Renderizar la nota de este beat en cada cuerda
            for s_idx in range(1, self.strings + 1):
                if state.string == s_idx:
                    if state.fret >= 0 and not is_sustain:
                        # Número de traste, centrado en la celda
                        cell = str(state.fret).rjust(cell_w, " ")
                    else:
                        # Sustain o descanso en cuerda al aire (oculto)
                        cell = "-" * cell_w
                else:
                    # Silencio en esta cuerda
                    cell = "-" * cell_w
                lines[s_idx].append(cell)
            previous_midi = current_midi

        # Combinar en texto con nombres de cuerda al inicio
        text_lines = []
        for s_idx in range(1, self.strings + 1):
            prefix = self._string_label(s_idx) + "|"
            text_lines.append(prefix + "".join(lines[s_idx]))
        return "\n".join(text_lines)
