import pandas as pd
import os

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_PATH = os.path.join(BASE_DIR, "data", "generated_ships.csv")


def load_dataset():
    df = pd.read_csv(DATA_PATH)

    df.columns = [c.strip().lower() for c in df.columns]
    df = df.fillna("unknown")

    return df