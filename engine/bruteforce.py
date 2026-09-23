import random
import csv

with open("data/seeds.csv", "w", newline="") as f:

    writer = csv.writer(f)
    writer.writerow(["seed"])

    for i in range(1_000_000):

        seed = hex(random.getrandbits(64))
        writer.writerow([seed])

        if i % 10000 == 0:
            print(i)