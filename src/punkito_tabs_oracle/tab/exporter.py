from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence, Tuple, Union

from music21 import articulations, clef, duration, instrument, note, stream


BassRouteItem = Union[
    Mapping[str, object],
    Tuple[int, int, int, float],
    Tuple[Optional[int], Optional[int], Optional[int], float],
]


@dataclass(frozen=True)
class ExportedRouteItem:
    midi_pitch: Optional[int]
    string_index: Optional[int]
    fret_number: Optional[int]
    duration_in_beats: float


class MusicXMLExporter:
    """Exporta una ruta de bajo a MusicXML usando music21.

    El exportador crea una sola parte con bajo eléctrico y agrega notas/rests
    cuantizados a partir de la salida del router DP.
    """

    def __init__(self, route_items: Sequence[BassRouteItem]):
        self.route_items = [self._normalize_item(item) for item in route_items]

    @staticmethod
    def _normalize_item(item: BassRouteItem) -> ExportedRouteItem:
        if isinstance(item, Mapping):
            midi_pitch = item.get("midi_pitch")
            string_index = item.get("string_index")
            fret_number = item.get("fret_number")
            duration_in_beats = item.get("duration_in_beats")
        else:
            if len(item) != 4:
                raise ValueError("Route tuples must contain exactly 4 elements.")
            midi_pitch, string_index, fret_number, duration_in_beats = item

        if duration_in_beats is None:
            raise ValueError("duration_in_beats is required for every route item.")

        return ExportedRouteItem(
            midi_pitch=None if midi_pitch is None else int(midi_pitch),
            string_index=None if string_index is None else int(string_index),
            fret_number=None if fret_number is None else int(fret_number),
            duration_in_beats=float(duration_in_beats),
        )

    @staticmethod
    def _to_quarter_length(beats: float) -> float:
        if beats < 0:
            raise ValueError("duration_in_beats cannot be negative.")
        return float(beats)

    @staticmethod
    def _string_number_to_music21(string_index: int) -> int:
        if string_index < 0:
            raise ValueError("string_index cannot be negative.")
        if string_index == 0 or string_index <= 3:
            return string_index + 1
        return string_index

    def build_part(self) -> stream.Part:
        part = stream.Part()
        part.append(instrument.ElectricBass())
        part.insert(0, clef.BassClef())

        for item in self.route_items:
            ql = self._to_quarter_length(item.duration_in_beats)
            if item.midi_pitch is None or item.string_index is None or item.fret_number is None:
                rest = note.Rest()
                rest.duration = duration.Duration(ql)
                part.append(rest)
                continue

            n = note.Note()
            n.pitch.midi = int(item.midi_pitch)
            n.duration = duration.Duration(ql)
            string_number = self._string_number_to_music21(int(item.string_index))
            fret_number = int(item.fret_number)
            n.articulations.append(articulations.StringIndication(string_number))
            n.articulations.append(articulations.FretIndication(fret_number))
            part.append(n)

        return part

    def write(self, filepath: Union[str, Path]) -> str:
        """Escribe el MusicXML al filepath indicado y devuelve la ruta escrita."""
        path = Path(filepath)
        score = stream.Score()
        score.insert(0, self.build_part())
        written_path = score.write("musicxml", fp=str(path))
        return str(written_path)
