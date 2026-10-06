"""Launch the dictionary window without blocking Praat's menu callback."""
import os
import subprocess
import sys
from pathlib import Path


def main():
    directory = Path(__file__).resolve().parent
    flags = 0
    if os.name == 'nt':
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([sys.executable, str(directory / 'run_speech_dictionaries.py')],
                     cwd=directory, creationflags=flags, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
