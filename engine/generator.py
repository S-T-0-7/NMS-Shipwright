import random
import pandas as pd
import os

# -----------------------------
# PATH SETUP (robust)
# -----------------------------
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "generated_ships.csv")

os.makedirs(DATA_DIR, exist_ok=True)

# -----------------------------
# SHIP FEATURE POOLS
# -----------------------------
ship_types = ["Fighter", "Sentinel", "Solar", "Explorer", "Hauler", "Exotic"]

cockpits = [
    "Sphere",
    "Sharp",
    "Dragonfly",
    "Longnose",
    "Compact",
    "Heavy"
]

wings = [
    "Single",
    "Double",
    "Triple",
    "Folded",
    "Organic",
    "Angular"
]

nose_types = [
    "Short",
    "Long",
    "Needle",
    "Flat"
]

engines = [
    "Single",
    "Twin",
    "Heavy"
]

top_parts = [
    "None",
    "Fin",
    "Antenna",
    "Spoiler"
]

bottom_parts = [
    "None",
    "Skid",
    "Pod"
]

side_parts = [
    "None",
    "Thruster",
    "Fin"
]

colors = [
    "White",
    "Black",
    "Blue",
    "Red",
    "Green",
    "Gold",
    "Silver"
]

classes = ["C", "B", "A", "S"]
# -----------------------------
# SEED GENERATION
# -----------------------------
def generate_seed():
    return hex(random.getrandbits(64))

# -----------------------------
# SHIP GENERATION (STRUCTURED VARIETY)
# -----------------------------
def generate_ship():
    ship_type = random.choice(ship_types)

    # avoid variable name collisions
    wing_choice = None
    cockpit_choice = None
    color_choice = None

    if ship_type == "Sentinel":
        cockpit_choice = random.choice(["Sphere", "Sharp", "Compact"])
        wing_choice = random.choice(["Folded", "Angular", "Organic"])
        color_choice = random.choice(["Blue", "Black", "Silver"])

    elif ship_type == "Fighter":
        cockpit_choice = random.choice(["Dragonfly", "Sharp", "Longnose"])
        wing_choice = random.choice(["Triple", "Double", "Single"])
        color_choice = random.choice(["Red", "White", "Black"])

    elif ship_type == "Exotic":
        cockpit_choice = random.choice(cockpits)
        wing_choice = random.choice(wings)
        color_choice = random.choice(["Gold", "White", "Silver"])

    else:
        cockpit_choice = random.choice(cockpits)
        wing_choice = random.choice(wings)
        color_choice = random.choice(colors)

    return {
        
        "seed": generate_seed(),
        "type": ship_type,
        "cockpit": cockpit_choice,
        "wings": wing_choice,
        "nose": random.choice(nose_types),
        "engine": random.choice(engines),
        "top": random.choice(top_parts),
        "bottom": random.choice(bottom_parts),
        "side": random.choice(side_parts),
        "class": random.choice(classes),
        "color": color_choice
    }

# -----------------------------
# DATASET GENERATION
# -----------------------------
def generate_dataset(n=10000):
    print(f"\n[INFO] Generating {n} ships...")

    data = []

    for i in range(n):
        if i % 1000 == 0:
            print(f"[INFO] Generated {i}/{n}")

        data.append(generate_ship())

    df = pd.DataFrame(data)

    df.to_csv(OUTPUT_PATH, index=False)

    print(f"\n[SUCCESS] Dataset saved to:")
    print(OUTPUT_PATH)

# -----------------------------
# MAIN ENTRY POINT
# -----------------------------
if __name__ == "__main__":
    print("[INFO] Generator starting...")
    generate_dataset(10000)
    print("[INFO] Generator finished.")