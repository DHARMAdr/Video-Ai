"""
__main__.py - makes `python -m shortsforge ...` work.

WHY it exists:
    When you run `python -m shortsforge`, Python looks for this file and runs it.
HOW it works:
    It just hands control to cli.main().
HOW TO IMPROVE:
    Nothing needed. Put new commands in cli.py.
"""

import sys

from .cli import main

sys.exit(main())
