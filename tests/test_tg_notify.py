"""Unit tests for tg-notify hook."""
import json
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta

# Allow importing the hook module from hooks/
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))
import importlib
tg = importlib.import_module("tg-notify")
