# Punkito Tabs Oracle: System Architecture Specification

This document details the software engineering design, directory layout, and structural flow of the Punkito Tabs Oracle engine.

## 1. Current State of the Repository (The Skeleton)

At this moment, the repository is structured as a professional, installable Python package adhering to **PEP 518**. Here is the responsibility mapping of each component:

```
punkito-tabs-oracle/
├── config/
│   ├── locales/
│   │   ├── en.json            # Dynamic string mapping for English UI
│   │   └── es.json            # Dynamic string mapping for Spanish UI
│   └── settings.toml          # Physics constraints (Tuning, weights, frets)
├── src/
│   └── punkito_tabs_oracle/
│       ├── __init__.py        # Packages exposure
│       ├── cli.py             # Orchestrator & CLI argument parser (Entry point)
│       ├── dsp/
│       │   └── pitch.py       # STUB: Empty interface for pYIN algorithms
│       ├── ml/
│       │   └── separator.py   # STUB: Empty interface for Spleeter/TensorFlow
│       └── tab/
│           └── router.py      # STUB: Empty interface for fretboard physical optimization
├── pyproject.toml             # Package metadata, executable registration & dependency locks
└── .gitignore                 # Binary and heavy data isolation rules
```

## 2. Functional Components of the Skeleton

### A. The Setup Metadata (pyproject.toml)

Instead of a simple execution script, your project is now registered in your Windows registry as an editable package.

Whenever you run the command `punkito-tabs` in your terminal (with the virtualenv activated), Windows knows it must invoke `punkito_tabs_oracle.cli:main` thanks to the `[project.scripts]` registration.

It locks down compatibility boundaries to prevent Python 3.11+ compilers from attempting to install incompatible TensorFlow binaries on Windows.

### B. Decoupled Internationalization (i18n via JSON)

The UI strings are entirely isolated from the executable code.

The orchestration engine in `cli.py` loads `config/locales/{lang}.json` dynamically based on the execution flags (`--lang en` or `--lang es`).

This pattern guarantees that adding support for a new language (e.g., Latin) only requires dropping a new `{lang}.json` file in `config/locales/` without modifying a single line of Python code.

## 3. The Signal & Algorithmic Pipeline (The Core to Populate)

Once we start writing code within the modules inside `src/`, the data will flow through three heavily decoupled processing layers:

```
[ Input Audio: Polyphonic Mix (.mp3/.wav) ]
                    │
                    ▼
┌───────────────────────────────────────┐
│           ml/separator.py             │
│  - Load Isolated Spleeter Model       │   (Runs U-Net Conv2D network via TensorFlow)
│  - Compute Masking Spectrogram        │
└───────────────────────────────────────┘
                    │
                    ▼
            [ Bass Stem (.wav) ]
                    │
                    ▼
┌───────────────────────────────────────┐
│            dsp/pitch.py               │
│  - Downsample signal to 22050Hz       │   (Uses Librosa pYIN tracking to estimate f0)
│  - Compute autocorrelation & HMM      │
└───────────────────────────────────────┘
                    │
                    ▼
            [ f0/Pitch Time Series ]
                    │
                    ▼
┌───────────────────────────────────────┐
│            tab/router.py              │
│  - Parse frequency to MIDI notes      │   (Heuristic / Dynamic Programming path-finder)
│  - Map notes to 4-string fretboard    │
│  - Apply transition-cost algorithms   │
└───────────────────────────────────────┘
                    │
                    ▼
        [ Print Optimized ASCII Tablature ]
```

## 4. Module Responsibilities

### ml/separator.py (The Heavy Lifter)

This module will host the neural network client. It imports TensorFlow and wraps Spleeter. Its only job is to:

1. Intake an arbitrary polyphonic audio file
2. Pass it through Spleeter's pre-trained 4-stem isolation model
3. Extract the bass stem
4. Return a normalized WAV file

**Input:** Polyphonic audio (MP3 or WAV)  
**Output:** Isolated bass stem (.wav)  
**Dependencies:** TensorFlow, Spleeter, Librosa

### dsp/pitch.py (The Precision Ear)

This module imports Librosa. It takes the `bass.wav` generated in the previous step, reads the raw samples, downsamples them to a manageable sample rate ($22.05 \text{ kHz}$), and applies the **Probabilistic YIN (pYIN)** algorithm to produce a robust pitch trajectory free of octave errors.

The output is a time-stamped series of frequency values representing the fundamental frequency ($f_0$) of the bass line over time.

**Input:** Bass stem (.wav)  
**Output:** f0 time series (MIDI notes or Hz values)  
**Dependencies:** Librosa, NumPy, SciPy

### tab/router.py (The Ergonomic Guitarist)

This is the pure algorithmic engine. It converts the $f_0$ frequencies to MIDI values. Because a bass guitar has overlapping note positions (e.g., the fifth fret on the E string is the same pitch as the open A string), we use **Dynamic Programming** to find the sequence of (string, fret) pairs that minimizes physical hand movement while respecting ergonomic constraints.

**Input:** f0 time series or MIDI sequence  
**Output:** ASCII tablature  
**Dependencies:** NumPy (for cost matrix computation)

## 5. Example Output

For a simple bass line on the open A and open E strings with some fifth-fret fills, the output might look like:

```
G|--------------------------------|
D|--------------------------------|
A|--------5---7---5---------------|
E|----5---------------7---5-------|
```

Where:
- Each vertical line represents a time step
- Numbers represent fret positions (0 = open string)
- Dashes represent silence or sustained notes on that string

---

## 6. Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Audio I/O** | Librosa | Load audio, compute spectrograms |
| **Neural Separation** | Spleeter + TensorFlow | Isolate bass stem |
| **Pitch Tracking** | Librosa (pYIN) | Estimate fundamental frequency |
| **Fretboard Routing** | NumPy + Custom DP | Optimize tab fingering |
| **CLI & Config** | Dynaconf, Click/Argparse | CLI orchestration, i18n |
| **Testing** | pytest | Unit and integration tests |

---

## 7. Design Principles

✅ **Modular:** Each stage (ML, DSP, Tab Routing) is independent and testable.  
✅ **Bilingual:** Configuration and UI strings are externalized to JSON.  
✅ **Pythonic:** Follows PEP 8, PEP 518, and modern Python packaging conventions.  
✅ **Extensible:** New languages, algorithms, or bass tunings can be added without core code changes.  
✅ **Documented:** Every module has clear input/output contracts.
