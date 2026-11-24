"""
JARVIS Ultimate - Main Entry Point
Run this file to start JARVIS
"""

import logging
_log = logging.getLogger(__name__)

import sys
from pathlib import Path

# Allow `python jarvis/main.py` from anywhere: make the project root importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.core.jarvis_ultimate import JARVISUltimate  # noqa: E402


def main():
    """Main entry point"""
    try:
        jarvis = JARVISUltimate()
        jarvis.run()
    except KeyboardInterrupt:
        _log.info("\n\nKeyboard interrupt - Shutting down")
    except Exception as e:
        _log.warning(f"FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
