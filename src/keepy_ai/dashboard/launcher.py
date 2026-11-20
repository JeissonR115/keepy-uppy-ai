from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    """Launch the optional Streamlit application."""
    try:
        from streamlit.web import cli as streamlit_cli
    except ImportError as error:
        raise SystemExit(
            "The dashboard requires the optional viz dependencies. "
            "Install them with `uv sync --extra viz`."
        ) from error
    app_path = Path(__file__).with_name("app.py")
    sys.argv = ["streamlit", "run", str(app_path), *sys.argv[1:]]
    streamlit_cli.main()
