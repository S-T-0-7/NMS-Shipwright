from engine.dataset import load_dataset

df = load_dataset()


def search_by_type(ship_type):
    return df[df["type"].str.lower() == ship_type.lower()]


def search_by_features(query):
    """
    simple multi-feature search (foundation for AI-like behavior)
    """
    q = query.lower()

    results = df[
        df["type"].str.lower().str.contains(q) |
        df["cockpit"].str.lower().str.contains(q) |
        df["wings"].str.lower().str.contains(q) |
        df["class"].str.lower().str.contains(q) |
        df["color"].str.lower().str.contains(q)
    ]

    return results


def run():
    while True:
        q = input("\nSearch (type/feature/exit): ")

        if q.lower() == "exit":
            break

        results = search_by_features(q)

        if results.empty:
            print("No results found")
        else:
            print("\n", results.to_string(index=False))


if __name__ == "__main__":
    run()