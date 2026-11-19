import logging
import sys
from pathlib import Path
import pandas as pd

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings
from src.features.builder import build_feature_dataset

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("build_features")

def main():
    # Rebuilding features changes the model contract. Publish matching models
    # and datasets together rather than overwriting files ignored by readers.
    from scripts.train_playing_time_release import main as rebuild_release
    rebuild_release(rebuild_base=True)


if __name__ == "__main__":
    main()
