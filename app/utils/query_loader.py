import os
import toml
from functools import lru_cache


def load_queries():
    # Get absolute path to queries folder
    base_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),  # goes to app/
        "queries"
    )

    # print("QUERY PATH =", base_path)
    # print("EXISTS =", os.path.exists(base_path))

    all_queries = {}

    for filename in os.listdir(base_path):
        if filename.endswith(".toml"):
            file_path = os.path.join(base_path, filename)
            data = toml.load(file_path)
            all_queries.update(data)

    return all_queries
