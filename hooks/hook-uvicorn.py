# hooks/hook-uvicorn.py
# Tells PyInstaller to include all of uvicorn's dynamically-imported modules.
# Without this, uvicorn silently fails at startup inside the frozen exe.

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hiddenimports = collect_submodules('uvicorn')
datas = collect_data_files('uvicorn')
