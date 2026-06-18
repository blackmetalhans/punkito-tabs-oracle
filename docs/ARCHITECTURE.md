# Punkito Tabs Oracle: Current Architecture (June 2026)

This document reflects the **current functional state** of the repository. Project Status: ✅ Functional MVP — ML, DSP, routing, and MusicXML export integrated and passing tests.

The current architecture separates concerns across ML, DSP, routing, and export so each stage can be tuned independently while preserving deterministic end-to-end behavior.

## 1. Implemented System Flow

```text
Input Audio File
   -> CLI validation (language, ffmpeg, path, extension)
   -> ML separation (Spleeter 4 stems)
   -> Isolated bass stem (bass.wav)
   -> DSP pitch tracking (pYIN + cubic interpolation)
   -> Beat-quantized f0 sequence
   -> Fretboard routing (dynamic programming)
   -> ASCII tablature output
   -> MusicXML export with technical string/fret metadata
```

## 2. Repository Layout and Responsibilities

```text
punkito-tabs-oracle/
├── config/
│   ├── locales/
│   │   ├── en.json
│   │   └── es.json
│   └── settings.toml
├── src/punkito_tabs_oracle/
│   ├── cli.py
│   ├── ml/separator.py
│   ├── dsp/pitch.py
│   └── tab/
│       ├── router.py
│       └── exporter.py
└── tests/
    ├── test_dsp.py
    └── test_tab.py
```

### `src/punkito_tabs_oracle/cli.py`
- Entry point for `punkito-tabs`.
- Loads i18n messages from `config/locales`.
- Validates input audio and `ffmpeg` availability.
- Orchestrates ML -> DSP -> TAB sequence.
- Exports `stems_output/<audio_name>/bass_tab.musicxml` after routing.

The CLI is intentionally thin: it coordinates stage boundaries, surfaces user-facing status/errors, and writes final artifacts without embedding DSP or routing logic.

### `src/punkito_tabs_oracle/ml/separator.py`
- `BassSeparator` wraps Spleeter (`spleeter:4stems`).
- Runs separation and stores outputs under `stems_output/<input_name>/`.
- Returns the generated `bass.wav` absolute path.

### `src/punkito_tabs_oracle/dsp/pitch.py`
- `PitchTracker.estimar_f0()` computes frame-level f0.
- Uses `librosa.pyin` first, then cubic interpolation for low-confidence or unvoiced frames.
- Applies RMS silence masking (`f0=0.0` in low-energy frames).
- `obtener_f0_por_pulso()` detects tempo/beats and returns beat-level median f0.

### `src/punkito_tabs_oracle/tab/router.py`
- `FretboardRouter` converts f0 to MIDI and finds ergonomic `(string, fret)` paths.
- Uses dynamic programming with transition cost terms loaded from `config/settings.toml`.
- Supports rests and renders 4-string ASCII tablature with bar separators every 4 beats.
- Emits grouped route events with `(midi_pitch, string_index, fret_number, duration_in_beats)` for downstream exporters.

### `src/punkito_tabs_oracle/tab/exporter.py`
- `MusicXMLExporter` builds a `music21` Electric Bass part in Bass Clef.
- Writes rhythmic notes/rests and preserves physical fingering via MusicXML `<technical>` metadata (`StringIndication` and `FretIndication`).
- Output is compatible with MuseScore, Guitar Pro, AlphaTab, and Songsterr-style rendering engines.

This guarantees interoperability: downstream notation tools receive both the musical event stream and the exact physical fingering selected by the router.

## 3. Test Coverage (Current)

### `tests/test_dsp.py`
- Validates pitch estimation accuracy on synthetic sine waves.
- Validates beat-quantized output behavior.

### `tests/test_tab.py`
- Validates open-string/low-fret decisions.
- Validates bar rendering in ASCII tab output.
- Validates rest handling.

## 4. Current Gaps

- No end-to-end integration tests covering full CLI + ML + DSP + TAB runtime chain.
- `config/settings.toml` contains instrument, router, and DSP parameters used at runtime.
- Heavy runtime dependencies (Spleeter/TensorFlow + Python version constraints) require controlled environment setup.

## 5. Immediate Next Milestones

1. Add integration tests for complete pipeline execution.
2. Add batch processing support over multiple input files.
3. Add a higher-level user interface (GUI/Web) on top of the current CLI.
