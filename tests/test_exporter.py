from pathlib import Path

from punkito_tabs_oracle.tab.exporter import MusicXMLExporter


def test_musicxml_exporter_writes_staff_tuning(tmp_path):
    route = [
        {"midi_pitch": 28, "string_index": 4, "fret_number": 0, "duration_in_beats": 1.0},
        {"midi_pitch": 33, "string_index": 3, "fret_number": 0, "duration_in_beats": 1.0},
    ]

    output_path = tmp_path / "bass_tab.musicxml"
    written = MusicXMLExporter(route, tempo_bpm=120.0).write(output_path)

    assert Path(written).exists()
    xml_text = Path(written).read_text(encoding="utf-8")
    assert "<staff-details>" in xml_text
    assert "<staff-lines>4</staff-lines>" in xml_text
    assert "<tuning-step>E</tuning-step>" in xml_text
    assert "<tuning-step>G</tuning-step>" in xml_text
