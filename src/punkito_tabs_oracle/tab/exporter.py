from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import List, Mapping, Optional, Sequence, Tuple, Union

from music21 import articulations, clef, duration, instrument, meter, note, pitch, stream, tempo, spanner

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
    articulation_type: str = "normal"  # 'normal' | 'dead' | 'legato'


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
            articulation_type = item.get("articulation_type", "normal")
        else:
            if len(item) < 4:
                raise ValueError("Route tuples must contain at least 4 elements.")
            midi_pitch, string_index, fret_number, duration_in_beats = item[:4]
            articulation_type = item[4] if len(item) > 4 else "normal"

        if duration_in_beats is None:
            raise ValueError("duration_in_beats is required for every route item.")

        return ExportedRouteItem(
            midi_pitch=None if midi_pitch is None else int(midi_pitch),
            string_index=None if string_index is None else int(string_index),
            fret_number=None if fret_number is None else int(fret_number),
            duration_in_beats=float(duration_in_beats),
            articulation_type=str(articulation_type) if articulation_type else "normal",
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
        """Build a MusicXML staff-details block for 5-string bass tuning.

        Enforces explicit 5-string bass tuning:
        - line 1 (highest): G2 (43 MIDI)
        - line 2: D2 (38 MIDI)
        - line 3: A1 (33 MIDI)
        - line 4: E1 (28 MIDI)
        - line 5 (lowest): B0 (23 MIDI)
        """
        staff_details = ET.Element("staff-details")
        ET.SubElement(staff_details, "staff-lines").text = "5"

        # Explicit mapping: line -> MIDI pitch
        explicit_tuning = [
            (1, 43, "G", 2),   # line 1: G2
            (2, 38, "D", 2),   # line 2: D2
            (3, 33, "A", 1),   # line 3: A1
            (4, 28, "E", 1),   # line 4: E1
            (5, 23, "B", 0),   # line 5: B0
        ]

        for line_num, midi_pitch, step, octave in explicit_tuning:
            tuning = ET.SubElement(staff_details, "staff-tuning", line=str(line_num))
            ET.SubElement(tuning, "tuning-step").text = step
            ET.SubElement(tuning, "tuning-octave").text = str(octave)

        return staff_details

    def build_part(self) -> stream.Part:
        """Builds a Part with proper articulation handling (dead notes, slurs, glissandos)."""
        part = stream.Part()
        part.append(instrument.ElectricBass())
        part.insert(0, meter.TimeSignature("4/4"))
        part.insert(0, tempo.MetronomeMark(number=self.tempo_bpm))
        part.insert(0, clef.BassClef())

        # Track legato sequences for slur/glissando rendering
        legato_sequence: List[Tuple[note.Note, int, int]] = []  # (note, string_index, fret_number)

        for item in self.route_items:
            ql = self._to_quarter_length(item.duration_in_beats)
            if item.midi_pitch is None or item.string_index is None or item.fret_number is None:
                # Flush any pending legato sequence
                self._flush_legato_sequence(part, legato_sequence)
                legato_sequence = []

                rest = note.Rest()
                rest.duration = duration.Duration(ql)
                part.append(rest)
                continue

            n = note.Note()
            n.pitch.midi = int(item.midi_pitch)
            n.duration = duration.Duration(ql)

            # Apply articulation-specific properties
            if item.articulation_type == "dead":
                n.notehead = "x"
            elif item.articulation_type == "legato":
                legato_sequence.append((n, int(item.string_index), int(item.fret_number)))

            # Always add string and fret metadata
            internal_idx = int(item.string_index)
            physical_string = self._internal_to_physical_string(internal_idx)
            fret_number = int(item.fret_number)
            n.articulations.append(articulations.StringIndication(physical_string))
            n.articulations.append(articulations.FretIndication(fret_number))

            part.append(n)

            # If not legato, flush the legato sequence
            if item.articulation_type != "legato":
                self._flush_legato_sequence(part, legato_sequence)
                legato_sequence = []

        # Final flush of pending legato
        self._flush_legato_sequence(part, legato_sequence)

        return part

    def _flush_legato_sequence(
        self, part: stream.Part, legato_sequence: List[Tuple[note.Note, int, int]]
    ) -> None:
        """Flush a legato sequence as either a Glissando (slide) or Slur.
        
        If notes change fret on the same string → Glissando (slide).
        If notes maintain same pitch/fret → no spanner (just sustain).
        Otherwise → Slur (simple legato).
        """
        if not legato_sequence or len(legato_sequence) < 2:
            return

        notes = [item[0] for item in legato_sequence]
        
        # Check if this is a slide: changing frets on the same string
        is_slide = self._is_slide_sequence(legato_sequence)
        
        if is_slide:
            # Use Glissando for slides
            for i in range(len(notes) - 1):
                gliss = spanner.Glissando(notes[i], notes[i + 1])
                gliss.lineType = "solid"
                part.append(gliss)
        else:
            # Check if all notes have the same pitch (sustain, no spanner needed)
            all_same_pitch = all(
                notes[i].pitch.midi == notes[0].pitch.midi for i in range(len(notes))
            )
            if not all_same_pitch:
                # Use Slur for simple legato articulation
                slur = spanner.Slur(notes)
                part.append(slur)

    def _is_slide_sequence(self, legato_sequence: List[Tuple[note.Note, int, int]]) -> bool:
        """Determine if a legato sequence represents a slide (glissando).
        
        Returns True if notes are on the same string with changing frets.
        """
        if len(legato_sequence) < 2:
            return False
        
        # Extract string and fret info
        first_string = legato_sequence[0][1]
        
        # Check if all notes are on the same string
        same_string = all(item[1] == first_string for item in legato_sequence)
        if not same_string:
            return False
        
        # Check if frets are changing
        frets = [item[2] for item in legato_sequence]
        changing_frets = not all(fret == frets[0] for fret in frets)
        
        return changing_frets

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
