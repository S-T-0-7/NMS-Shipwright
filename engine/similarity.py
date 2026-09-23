from engine.dataset import load_dataset

df = load_dataset()

# -------------------------
# WEIGHTS
# -------------------------
WEIGHTS = {
    "type": 5,
    "cockpit": 4,
    "wings": 4,
    "class": 2,
    "color": 1
}


def score_ship(row, target):

    score = 0
    max_score = 0

    for field, weight in WEIGHTS.items():

        if target.get(field) is not None:

            max_score += weight

            if row[field] == target[field]:
                score += weight

    if max_score == 0:
        return 0

    return round(score / max_score, 3)


def find_similar(target, top_n=10):

    results = []

    for _, row in df.iterrows():

        similarity = score_ship(row, target)

        results.append({
            "score": similarity,
            "seed": row["seed"],
            "type": row["type"],
            "cockpit": row["cockpit"],
            "wings": row["wings"],
            "class": row["class"],
            "color": row["color"]
        })

    results.sort(key=lambda x: x["score"], reverse=True)

    return results[:top_n]


if __name__ == "__main__":

    target = {
        "type": "Solar",
        "cockpit": "Longnose",
        "wings": "Organic",
        "class": "S",
        "color": "Green"
    }

    matches = find_similar(target)

    print("\nTOP MATCHES\n")

    for ship in matches:
        print(ship)