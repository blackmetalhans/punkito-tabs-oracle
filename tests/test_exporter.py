from pathlib import Path

from punkito_tabs_oracle.tab.exporter import MusicXMLExporter


def test_musicxml_exporter_writes_staff_tuning(tmp_path):
    route = [
        {"midi_pitch": 43, "string_index": 1, "fret_number": 0, "duration_in_beats": 1.0},  # G2, string 1
        {"midi_pitch": 38, "string_index": 2, "fret_number": 0, "duration_in_beats": 1.0},  # D2, string 2
    ]

    output_path = tmp_path / "bass_tab.musicxml"
    written = MusicXMLExporter(route, tempo_bpm=120.0).write(output_path)

    assert Path(written).exists()
    xml_text = Path(written).read_text(encoding="utf-8")
    assert "<staff-details>" in xml_text
    assert "<staff-lines>5</staff-lines>" in xml_text
    assert "<tuning-step>G</tuning-step>" in xml_text
    assert "<tuning-step>D</tuning-step>" in xml_text
    assert "<tuning-step>B</tuning-step>" in xml_text  # B0 for 5-string bass

