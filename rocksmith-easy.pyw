# Windows: double-click this to open the GUI with no console window behind it.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rseasy.cli import main

sys.exit(main(["gui"]))
