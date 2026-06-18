from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence, Tuple, Union

from music21 import articulations, clef, duration, instrument, meter, note, pitch, stream, tempo

from punkito_tabs_oracle.settings import load_settings


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

    El exportador crea una sola parte con bajo eléctrico, agrega notas/rests
    cuantizados a partir de la salida del router DP y enriquece el XML con
    metadata de afinación y tempo para software de tablatura.
    """

    def __init__(
        self,
        route_items: Sequence[BassRouteItem],
        tempo_bpm: Optional[float] = None,
        settings_path: Optional[Path] = None,
    ):
        self.route_items = [self._normalize_item(item) for item in route_items]

        settings = load_settings(settings_path)
        instrument_settings = settings.get("instrument", {})
        tuning_midi = instrument_settings.get("tuning_midi", [])
        if not tuning_midi:
            raise ValueError("instrument.tuning_midi is required for MusicXML export")

        self.tuning_midi = [int(value) for value in tuning_midi]
        self.tempo_bpm = float(tempo_bpm) if tempo_bpm is not None else 120.0

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
        """Return the physical string number used by the route model."""
        if string_index < 1:
            raise ValueError("string_index must be 1-based.")
        return int(string_index)

    def _internal_to_physical_string(self, internal_string_index: int) -> int:
        """Convert internal (1-based) string index to physical music21 string number.

        Internal indices in the router are 1-based with 1 = highest pitch.
        The tuning_midi is stored low->high, so compute physical mapping as:
            physical = total_strings - (internal - 1)
        This ensures string 1 is the highest-pitched string in MusicXML.
        """
        total = len(self.tuning_midi)
        if internal_string_index < 1 or internal_string_index > total:
            raise ValueError("internal_string_index out of range")
        return int(total - (internal_string_index - 1))

    def _build_staff_details(self) -> ET.Element:
        """Build a MusicXML staff-details block for the configured tuning.

        The settings.tuning_midi is ordered low-to-high. MusicXML expects staff-tuning
        lines numbered top-to-bottom where line="1" is the highest string. Compute
        the line attribute using the physical mapping described above.
        """
        staff_details = ET.Element("staff-details")
        ET.SubElement(staff_details, "staff-lines").text = str(len(self.tuning_midi))

        total = len(self.tuning_midi)
        # tuning_midi is low->high; assign each entry its physical (top-down) line number
        for idx, midi_pitch in enumerate(self.tuning_midi):
            physical_line = total - idx
            tuning = ET.SubElement(staff_details, "staff-tuning", line=str(physical_line))
            p = pitch.Pitch(midi=int(midi_pitch))
            ET.SubElement(tuning, "tuning-step").text = p.step
            ET.SubElement(tuning, "tuning-octave").text = str(p.octave)

        return staff_details

    def build_part(self) -> stream.Part:
        part = stream.Part()
        part.append(instrument.ElectricBass())
        part.insert(0, meter.TimeSignature("4/4"))
        part.insert(0, tempo.MetronomeMark(number=self.tempo_bpm))
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
            # Convert internal router string index (1-based) to physical music21 string number
            internal_idx = int(item.string_index)
            physical_string = self._internal_to_physical_string(internal_idx)
            fret_number = int(item.fret_number)
            n.articulations.append(articulations.StringIndication(physical_string))
            n.articulations.append(articulations.FretIndication(fret_number))
            part.append(n)

        return part

    def write(self, filepath: Union[str, Path]) -> str:
        """Escribe el MusicXML al filepath indicado y devuelve la ruta escrita."""
        path = Path(filepath)
        score = stream.Score()
        score.insert(0, self.build_part())

        written_path = score.write("musicxml", fp=str(path))
        xml_text = Path(written_path).read_text(encoding="utf-8")
        root = ET.fromstring(xml_text.encode("utf-8"))

        for part in root.findall(".//part"):
            attributes = part.find("measure/attributes")
            if attributes is None:
                continue
            if attributes.find("staff-details") is not None:
                continue
            attributes.append(self._build_staff_details())

        Path(written_path).write_text(
            ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8"),
            encoding="utf-8",
        )

        return str(written_path)
