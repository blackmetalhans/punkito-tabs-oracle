# Punkito Tabs Oracle: Current Architecture (June 2026)

This document reflects the **current functional state** of the repository.

## 1. Implemented System Flow

```text
Input Audio File
   -> CLI validation (language, ffmpeg, path, extension)
   -> ML separation (Spleeter 4 stems)
   -> Isolated bass stem (bass.wav)
   -> DSP pitch tracking (pYIN + YIN fallback)
   -> Beat-quantized f0 sequence
   -> Fretboard routing (dynamic programming)
   -> ASCII tablature output
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
│   └── tab/router.py
└── tests/
    ├── test_dsp.py
    └── test_tab.py
```

### `src/punkito_tabs_oracle/cli.py`
- Entry point for `punkito-tabs`.
- Loads i18n messages from `config/locales`.
- Validates input audio and `ffmpeg` availability.
- Orchestrates ML -> DSP -> TAB sequence.

### `src/punkito_tabs_oracle/ml/separator.py`
- `BassSeparator` wraps Spleeter (`spleeter:4stems`).
- Runs separation and stores outputs under `stems_output/<input_name>/`.
- Returns the generated `bass.wav` absolute path.

### `src/punkito_tabs_oracle/dsp/pitch.py`
- `PitchTracker.estimar_f0()` computes frame-level f0.
- Uses `librosa.pyin` first, with fallback to `librosa.yin` when voiced confidence is too low.
- Applies RMS silence masking (`f0=0.0` in low-energy frames).
- `obtener_f0_por_pulso()` detects tempo/beats and returns beat-level median f0.

### `src/punkito_tabs_oracle/tab/router.py`
- `FretboardRouter` converts f0 to MIDI and finds ergonomic `(string, fret)` paths.
- Uses dynamic programming with transition cost terms for movement and string preference.
- Supports rests and renders 4-string ASCII tablature with bar separators every 4 beats.

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
- `config/settings.toml` exists but is currently empty and not wired into runtime parameters.
- Heavy runtime dependencies (Spleeter/TensorFlow + Python version constraints) require controlled environment setup.

## 5. Immediate Next Milestones

1. Add integration tests for complete pipeline execution.
2. Move router/DSP tunables into `config/settings.toml` and load them from CLI runtime.
3. Add batch processing mode and higher-level user interface options.
