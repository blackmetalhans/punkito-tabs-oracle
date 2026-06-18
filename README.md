# 🎸 Punkito Tabs Oracle for Bass

**Language / Idioma:** 🇺🇸 English | [🇪🇸 Leer en Español](./README.es.md)

> **AI-powered bass isolation and tablature transcription system** — Convert polyphonic audio into playable bass guitar tabs.

✅ **Project Status:** Functional MVP — ML, DSP, routing, and MusicXML export integrated and passing tests.

Punkito Tabs Oracle is designed as a deterministic audio-to-tab workflow: each stage has a specific responsibility, and each output can be inspected independently. This makes the system practical both for iterative DSP development and for downstream notation workflows that need reproducible physical fingering.

## 🎯 What This Project Does

Punkito Tabs Oracle is an audio processing pipeline that:

1. **Isolates the bass stem** from polyphonic audio using Spleeter.
2. **Detects fundamental pitch (f0)** with `librosa.pyin` and cubic interpolation for low-confidence frames.
3. **Quantizes pitches by beat** to improve readability.
4. **Maps notes to fretboard positions** using dynamic-programming routing.
5. **Generates ASCII tablature** for 4-string bass.
6. **Exports MusicXML** with physical string/fret metadata compatible with MuseScore, Guitar Pro, AlphaTab, and Songsterr-like rendering engines.

## 🏗️ Implemented Architecture

```mermaid
flowchart TD
    A[Input audio] --> B[ML: BassSeparator - Spleeter 4 stems]
    B --> C[Isolated bass.wav]
    C --> D[DSP: PitchTracker - pYIN + cubic interpolation + RMS silence filter]
    D --> E[Beat-quantized f0 pulses]
    E --> F[Tab: FretboardRouter - DP cost optimization]
    F --> G[ASCII tab output]
    F --> H[MusicXMLExporter - notation+tab export with technical metadata]
```

## 📂 Project Structure

```
punkito-tabs-oracle/
├── config/
│   ├── locales/
│   │   ├── en.json
│   │   └── es.json
│   └── settings.toml          # Runtime DSP/router/instrument parameters
├── docs/
│   └── ARCHITECTURE.md
├── src/
│   └── punkito_tabs_oracle/
│       ├── cli.py             # Pipeline orchestration CLI
│       ├── dsp/pitch.py       # pYIN + interpolation + beat quantization
│       ├── ml/separator.py    # Spleeter wrapper for bass stem isolation
│       └── tab/
│           ├── router.py      # Dynamic-programming fret routing + ASCII tab
│           └── exporter.py    # MusicXML export with string/fret metadata
└── tests/
    ├── test_dsp.py
    └── test_tab.py
```

## 🚀 Installation & Setup

### Requirements
- **Python 3.10** (required for dependency compatibility)
- `ffmpeg` available in system PATH

### Install

```bash
pip install -e .[dev]
```

## 💻 Current Functional Progress

### ✅ CLI Orchestration
- Localized messages in English/Spanish.
- Validates audio file existence and extension.
- Validates `ffmpeg` before processing.
- Runs the ML → DSP → TAB pipeline sequence.
- Saves `stems_output/<audio_name>/bass_tab.musicxml` after routing.

The CLI now emits two complementary tab artifacts from the same routed sequence: a human-readable ASCII preview and a structured `.musicxml` file intended for notation editors and rendering engines.

### ✅ ML Layer (`ml/separator.py`)
- Uses `spleeter:4stems` model.
- Exports isolated bass stem to `./stems_output/<audio_name>/bass.wav`.
- Includes dependency and output validation.

### ✅ DSP Layer (`dsp/pitch.py`)
- pYIN-based f0 estimation in 30–400 Hz.
- Cubic interpolation for low-confidence / unvoiced frames.
- RMS-based silence masking.
- Beat tracking + median f0 quantization per beat.

### ✅ TAB Layer (`tab/router.py`)
- Converts Hz → MIDI.
- Computes ergonomic state path (string/fret) with dynamic programming.
- Loads router and DSP tunables from `config/settings.toml`.
- Handles rests.
- Renders 4-line ASCII tablature with bar separators every 4 beats.
- Produces structured route events (`midi_pitch`, `string_index`, `fret_number`, `duration_in_beats`) for MusicXML export.

### ✅ MusicXML Layer (`tab/exporter.py`)
- Builds a `music21` Electric Bass part with Bass Clef.
- Encodes physical fingering into `<technical>` nodes via `StringIndication` and `FretIndication`.
- Preserves rests and beat durations in exported notation.
- Compatible with MuseScore, Guitar Pro, AlphaTab, and Songsterr-style rendering pipelines.

Because the exporter carries the exact DP-selected string/fret data, external notation software can reproduce the intended fingering instead of re-guessing positions from pitch only.

## 🔄 Pending / In Progress

- [x] Implement pitch tracking module.
- [x] Implement bass stem separation wrapper.
- [x] Implement fretboard routing and tab rendering.
- [ ] Add end-to-end integration tests for full CLI pipeline.
- [x] Integrate runtime tunables from `config/settings.toml`.
- [ ] Add batch mode and GUI.

## 📊 Testing
To avoid import errors, do not mutate PYTHONPATH. Ensure the package is installed in editable mode first:

```bash
pip install -e .[dev]
pytest -v
```

Current automated coverage includes:
- DSP pitch estimation and beat quantization behavior.
- Tab routing decisions and ASCII rendering.
- MusicXML route event grouping used by the exporter.

## 🎓 Documentation

- **[ARCHITECTURE.md](./docs/ARCHITECTURE.md)** — Current architecture and module responsibilities.

## 🔧 Installation & Quick Validation

1. Ensure Python 3.10 and ffmpeg are installed and on PATH.
2. Install package and dev deps: pip install -e .[dev]
3. Run tests: pytest -q
4. Quick example (generate MusicXML for input.wav):
   - punkito-tabs ./path/to/input.wav --lang en
   - Result: stems_output/<input_name>/bass_tab.musicxml

### Python client (programmatic)

A minimal Python client is provided to run the pipeline from other Python code:

```py
from punkito_tabs_oracle.client import run_pipeline
res = run_pipeline('path/to/input.wav', lang='en')
print(res['musicxml'])
```

The returned dict contains: 'bass_stem', 'musicxml', 'ascii_tab', 'bpm', 'route_events'.

### Quick run from the repository root

If you want the simplest path for local execution, use the root-level client:

```bash
python client.py ./path/to/input.wav --lang en
```

This will generate the usual output under `stems_output/<input_name>/` and write `bass_tab.musicxml` next to the isolated bass stem.

---

**Last Updated:** June 2026
