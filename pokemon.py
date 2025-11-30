# pokemon.py
# Loads the specific CSV format provided (with against_X columns).

import csv
import os
from typing import Dict, Optional

DEFAULT_CSV = "pokemon_data.csv"


def load_csv(path: str = DEFAULT_CSV) -> Dict[str, Dict]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"CSV not found at {path}. Please ensure pokemon_data.csv is present.")

    d = {}
    # Use utf-8-sig to handle potential BOM from Excel saves
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f, delimiter=',')
        for row in reader:
            # Handle possible name keys
            name = row.get("name") or row.get("japanese_name") or ""
            key = name.strip().lower()

            # Skip empty rows
            if not key:
                continue

            try:
                # We store the raw_row because it contains all the 'against_fire', 'against_bug' etc.
                # which are needed for Type Effectiveness calculations in battle.py.
                d[key] = {
                    "name": name,
                    "hp": int(row.get("hp") or 0),
                    "attack": int(row.get("attack") or 0),
                    "defense": int(row.get("defense") or 0),
                    "sp_attack": int(row.get("sp_attack") or 0),
                    "sp_defense": int(row.get("sp_defense") or 0),
                    "speed": int(row.get("speed") or 0),
                    "type1": (row.get("type1") or "").strip().lower(),
                    "type2": (row.get("type2") or "").strip().lower(),
                    "raw_row": row
                }
            except Exception as e:
                print(f"[POKEMON] Skipping bad row '{name}': {e}")
    return d


def get_pokemon(pokemon_db: Dict[str, Dict], name: str) -> Optional[Dict]:
    if name is None:
        return None
    return pokemon_db.get(name.strip().lower())