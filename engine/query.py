from engine.dataset import load_dataset

df = load_dataset()


# -----------------------------
# MENU SYSTEM
# -----------------------------
def choose_option(column_name):

    options = sorted(df[column_name].dropna().unique())

    print(f"\nSelect {column_name.upper()}")
    print("0) Any")

    for i, option in enumerate(options, start=1):
        print(f"{i}) {option}")

    while True:
        try:
            choice = int(input("Choice: "))

            if choice == 0:
                return None

            if 1 <= choice <= len(options):
                return options[choice - 1]

            print("Invalid selection.")

        except ValueError:
            print("Enter a number.")


# -----------------------------
# SEARCH ENGINE
# -----------------------------
def find_ships(
    ship_type=None,
    cockpit=None,
    wings=None,
    ship_class=None,
    color=None,
    limit=50
):

    results = df.copy()

    if ship_type:
        results = results[results["type"] == ship_type]

    if cockpit:
        results = results[results["cockpit"] == cockpit]

    if wings:
        results = results[results["wings"] == wings]

    if ship_class:
        results = results[results["class"] == ship_class]

    if color:
        results = results[results["color"] == color]

    return results.head(limit)


# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":

    print("\n======================")
    print(" NMS SHIP FINDER")
    print("======================")

    ship_type = choose_option("type")
    cockpit = choose_option("cockpit")
    wings = choose_option("wings")
    ship_class = choose_option("class")
    color = choose_option("color")

    results = find_ships(
        ship_type=ship_type,
        cockpit=cockpit,
        wings=wings,
        ship_class=ship_class,
        color=color
    )

    print("\n======================")
    print(" RESULTS")
    print("======================\n")

    if len(results) == 0:
        print("No ships found.\n")
    else:
        print(results.to_string(index=False))
        print(f"\nFound {len(results)} ships.\n")