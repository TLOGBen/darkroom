"""`python -m darkroom ...`: entry point of the core library's own small command line (see darkroom._cli).

This is not the App's CLI (`python -m darkroom_app.cli`); it only exists to apply one preset to one photo or to
scan a preset folder without starting anything else. The process exit code is whatever `_cli.main` returns.
"""
import sys

from ._cli import main

sys.exit(main())
