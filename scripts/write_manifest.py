"""Write manifest.json for a folder. Usage: python scripts/write_manifest.py <folder>"""
import sys
from pathlib import Path

from analogft.drive_check import write_manifest

if __name__ == "__main__":
    print(f"manifest written: {write_manifest(Path(sys.argv[1]))}")
