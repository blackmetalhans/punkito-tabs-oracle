#!/usr/bin/env python3
"""Release-facing Python client for Punkito Tabs Oracle.

This file lives at the repository root so it can be copied easily into a future
release package or used directly by developers as a lightweight entry point.
"""

from pathlib import Path
from typing import Any, Dict, Optional, Union


def _resolve_path(value: Union[str, Path]) -> Path:
    return Path(value).expanduser().resolve()


def run_pipeline(
    audio_file: Union[str, Path],
    lang: str = "en",
    settings_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Run the full pipeline programmatically and return artifact metadata."""
    from punkito_tabs_oracle.client import run_pipeline as _run_pipeline

    return _run_pipeline(
        audio_file=audio_file,
        lang=lang,
        settings_path=settings_path,
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run Punkito Tabs Oracle programmatically from the repository root."
    )
    parser.add_argument("audio_file", type=str, help="Path to the input audio file")
    parser.add_argument("--lang", default="en", choices=("en", "es"), help="CLI language")
    parser.add_argument(
        "--settings",
        default=None,
        help="Optional path to config/settings.toml override",
    )
    args = parser.parse_args()

    result = run_pipeline(args.audio_file, lang=args.lang, settings_path=args.settings)
    print("bass_stem:", result["bass_stem"])
    print("musicxml:", result["musicxml"])
    print("bpm:", result["bpm"])
    print("ascii_tab:\n", result["ascii_tab"])


if __name__ == "__main__":
    main()
