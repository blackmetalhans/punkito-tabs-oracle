from pathlib import Path
from typing import Any, Dict, Optional

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


def resolve_settings_path(settings_path: Optional[Path] = None) -> Path:
    if settings_path is not None:
        return Path(settings_path)
    return Path(__file__).resolve().parents[2] / "config" / "settings.toml"


def load_settings(settings_path: Optional[Path] = None) -> Dict[str, Any]:
    path = resolve_settings_path(settings_path)
    if not path.exists():
        raise FileNotFoundError(f"Settings file not found: {path}")
    with path.open("rb") as fh:
        return tomllib.load(fh)
