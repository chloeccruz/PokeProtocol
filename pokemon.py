# pokemon.py
# loads pokemon_data.csv, provides lookup functions

import csv
import os
from typing import Dict, Optional

DEFAULT_CSV = "pokemon_data.csv"

def load_csv(path: str = DEFAULT_CSV) -> Dict[str, Dict]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"CSV not found at {path}. Place your provided CSV as {path}")
    d = {}
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=',')
        for row in reader:
            # Normalize name key to lower for easy lookup
            name = row.get("name") or row.get("japanese_name") or ""
            key = name.strip().lower()
            try:
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
                print("[POKEMON] row parse error for", name, e)
    return d

def get_pokemon(pokemon_db: Dict[str, Dict], name: str) -> Optional[Dict]:
    if name is None:
        return None
    return pokemon_db.get(name.strip().lower())
