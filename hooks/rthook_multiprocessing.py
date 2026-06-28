# hooks/rthook_multiprocessing.py
# PyInstaller runtime hook — must be executed before any app code.
# Fixes the "freeze_support" error that occurs when Python's multiprocessing
# module is used inside a frozen (PyInstaller) Windows executable.

import multiprocessing
import sys

if sys.platform == 'win32':
    multiprocessing.freeze_support()
