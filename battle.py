# battle.py
# Implements BattleState, turn logic, and Type Effectiveness lookup.

import threading
import time
import ast
from typing import Dict, Any
from pokemon import get_pokemon
from messages import make_ack, serialize_message


def compute_damage(attacker_stat: float, defender_stat: float, base_power: float,
                   type_effectiveness: float = 1.0, boost_multiplier: float = 1.0, level: int = 50) -> int:
    """
    Standard Damage Formula from RFC Protocol Docs
    """
    if defender_stat <= 0:
        defender_stat = 1.0

    part1 = (2 * level) / 5
    part2 = part1 + 2

    ratio = attacker_stat / defender_stat

    part3 = part2 * base_power * ratio
    part4 = part3 / 50.0
    part5 = part4 + 2.0

    damage = part5 * type_effectiveness * boost_multiplier
    damage_int = int(round(damage))

    return max(1, damage_int)


class BattleState:
    def __init__(self, my_name: str, my_pokemon_name: str, my_pokemon: Dict,
                 peer_name: str = None, peer_pokemon_name: str = None, peer_pokemon: Dict = None):
        self.lock = threading.Lock()
        self.my_name = my_name
        self.my_pokemon_name = my_pokemon_name
        self.peer_name = peer_name or "Peer"
        self.peer_pokemon_name = peer_pokemon_name

        self.my_pokemon = dict(my_pokemon) if my_pokemon else {}
        self.peer_pokemon = dict(peer_pokemon) if peer_pokemon else {}

        self.my_hp = self.my_pokemon.get("hp", 100)
        self.peer_hp = self.peer_pokemon.get("hp", 100)

        self.turn_owner_is_me = False
        self.stat_boosts = {"special_attack_uses": 5, "special_defense_uses": 5}

    def apply_damage_to_peer(self, dmg: int):
        with self.lock:
            self.peer_hp = max(0, int(self.peer_hp - dmg))

    def apply_damage_to_me(self, dmg: int):
        with self.lock:
            self.my_hp = max(0, int(self.my_hp - dmg))

    def is_over(self):
        with self.lock:
            if self.my_hp <= 0:
                return True, (self.peer_pokemon_name, self.my_pokemon_name)
            if self.peer_hp <= 0:
                return True, (self.my_pokemon_name, self.peer_pokemon_name)
            return False, None


def make_handler(battle_state: BattleState, pokemon_db, node, role="joiner", verbose=False):
    # Simple move database
    move_db = {
        "tackle": {"base_power": 40, "damage_category": "physical", "type": "normal"},
        "scratch": {"base_power": 40, "damage_category": "physical", "type": "normal"},
        "thunderbolt": {"base_power": 90, "damage_category": "special", "type": "electric"},
        "flamethrower": {"base_power": 90, "damage_category": "special", "type": "fire"},
        "hydro pump": {"base_power": 110, "damage_category": "special", "type": "water"},
        "vine whip": {"base_power": 45, "damage_category": "physical", "type": "grass"},
        "earthquake": {"base_power": 100, "damage_category": "physical", "type": "ground"},
        "psychic": {"base_power": 90, "damage_category": "special", "type": "psychic"},
    }

    def lookup_move(name):
        return move_db.get(name.lower(), {"base_power": 50, "damage_category": "physical", "type": "normal"})

    def get_effectiveness(move_type, defender_pokemon):
        """
        Looks up the multiplier in the defender's CSV data (raw_row).
        e.g., if move is 'fire', looks for 'against_fire' in the defender's data.
        """
        if not defender_pokemon or "raw_row" not in defender_pokemon:
            return 1.0

        key = f"against_{move_type.lower()}"
        raw_row = defender_pokemon["raw_row"]

        try:
            return float(raw_row.get(key, 1.0))
        except:
            return 1.0

    def handler(msg: Dict[str, str], addr, node_ref):
        mtype = msg.get("message_type")
        if verbose and mtype:
            print(f"[HANDLER] Got {mtype}")

        # --- Handshake ---
        if mtype == "HANDSHAKE_REQUEST":
            if role == "host":
                seed = int(time.time()) & 0x7fffffff
                resp = {"message_type": "HANDSHAKE_RESPONSE", "seed": seed}
                node_ref.send(resp, addr)
                print(f"[HANDSHAKE] Sent seed {seed}")

        elif mtype == "HANDSHAKE_RESPONSE":
            if role == "joiner":
                print(f"[HANDSHAKE] Connected! Seed: {msg.get('seed')}")

        elif mtype == "SPECTATOR_REQUEST":
            if role == "host":
                node_ref.send({"message_type": "HANDSHAKE_RESPONSE", "seed": 0}, addr)

        # --- Setup ---
        elif mtype == "BATTLE_SETUP":
            pname = msg.get("pokemon_name")
            peer_data_str = msg.get("pokemon")

            p = None
            # 1. Try to parse the full dictionary sent by the peer
            if peer_data_str:
                try:
                    # It comes as a string representation of a dict
                    p = ast.literal_eval(peer_data_str)
                except:
                    print("[SETUP] Could not parse peer pokemon data, falling back to local DB.")

            # 2. Fallback to local DB lookup if parsing failed or data missing
            if not p or not isinstance(p, dict):
                p = get_pokemon(pokemon_db, pname)

            battle_state.peer_pokemon_name = pname
            battle_state.peer_pokemon = p or {}
            battle_state.peer_hp = p.get("hp", 100) if p else 100
            print(f"[SETUP] Opponent chose {pname} (HP: {battle_state.peer_hp})")

        # --- Battle Logic ---
        elif mtype == "ATTACK_ANNOUNCE":
            move = msg.get("move_name", "tackle")
            seq = int(msg.get("sequence_number", "0") or 0)
            print(f"[TURN] Opponent announced {move}")

            node_ref.send({"message_type": "DEFENSE_ANNOUNCE"}, addr)
            node_ref._last_incoming_attack = {"move_name": move, "sequence": seq}

        elif mtype == "DEFENSE_ANNOUNCE":
            print("[TURN] Calculating damage...")
            last_my = getattr(node_ref, "_my_last_announced_move", {"move_name": "tackle"})
            moveinfo = lookup_move(last_my["move_name"])

            if moveinfo["damage_category"] == "physical":
                atk = battle_state.my_pokemon.get("attack", 50)
                dfn = battle_state.peer_pokemon.get("defense", 50)
            else:
                atk = battle_state.my_pokemon.get("sp_attack", 50)
                dfn = battle_state.peer_pokemon.get("sp_defense", 50)

            # Get effectiveness from CSV data
            eff = get_effectiveness(moveinfo["type"], battle_state.peer_pokemon)

            dmg = compute_damage(atk, dfn, moveinfo["base_power"], type_effectiveness=eff)
            battle_state.apply_damage_to_peer(dmg)

            report = {
                "message_type": "CALCULATION_REPORT",
                "attacker": battle_state.my_pokemon_name,
                "move_used": last_my["move_name"],
                "remaining_health": battle_state.my_hp,
                "damage_dealt": dmg,
                "defender_hp_remaining": battle_state.peer_hp,
                "status_message": f"Used {last_my['move_name']} (x{eff})",
            }
            node_ref.send(report, addr)

        elif mtype == "CALCULATION_REPORT":
            print("[TURN] Verifying report...")
            attacker = msg.get("attacker", "")
            move_name = msg.get("move_used", "tackle")
            moveinfo = lookup_move(move_name)

            if attacker.lower() == battle_state.peer_pokemon_name.lower():
                # Peer attacked Me
                if moveinfo["damage_category"] == "physical":
                    atk = battle_state.peer_pokemon.get("attack", 50)
                    dfn = battle_state.my_pokemon.get("defense", 50)
                else:
                    atk = battle_state.peer_pokemon.get("sp_attack", 50)
                    dfn = battle_state.my_pokemon.get("sp_defense", 50)

                # Check effectiveness against ME
                eff = get_effectiveness(moveinfo["type"], battle_state.my_pokemon)

                local_calc = compute_damage(atk, dfn, moveinfo["base_power"], type_effectiveness=eff)
                reported_dmg = int(msg.get("damage_dealt", "0") or 0)

                if local_calc == reported_dmg:
                    battle_state.apply_damage_to_me(local_calc)
                    node_ref.send({"message_type": "CALCULATION_CONFIRM"}, addr)
                    print(f"[TURN] Verified. Took {local_calc} dmg.")
                else:
                    print(f"[DISCREPANCY] Local: {local_calc}, Remote: {reported_dmg}")
                    rr = {
                        "message_type": "RESOLUTION_REQUEST",
                        "attacker": attacker,
                        "move_used": move_name,
                        "damage_dealt": local_calc,
                        "defender_hp_remaining": battle_state.my_hp
                    }
                    node_ref.send(rr, addr)
            else:
                # I attacked Peer (Just check HP sync)
                reported_hp = int(msg.get("defender_hp_remaining", "0") or 0)
                if reported_hp == battle_state.peer_hp:
                    node_ref.send({"message_type": "CALCULATION_CONFIRM"}, addr)
                else:
                    # Sync error on their end
                    rr = {
                        "message_type": "RESOLUTION_REQUEST",
                        "attacker": attacker,
                        "move_used": move_name,
                        "damage_dealt": int(msg.get("damage_dealt", "0") or 0),
                        "defender_hp_remaining": battle_state.peer_hp
                    }
                    node_ref.send(rr, addr)

        elif mtype == "CALCULATION_CONFIRM":
            battle_state.turn_owner_is_me = not battle_state.turn_owner_is_me
            print(f"[TURN] End of turn. My turn? {battle_state.turn_owner_is_me}")
            over, result = battle_state.is_over()
            if over:
                winner, loser = result
                go = {"message_type": "GAME_OVER", "winner": winner, "loser": loser}
                node_ref.send(go, addr)

        elif mtype == "RESOLUTION_REQUEST":
            # For simplicity in this assignment, we accept the Resolution Request
            their_hp = int(msg.get("defender_hp_remaining", "0") or 0)
            attacker = msg.get("attacker", "")
            if attacker.lower() == battle_state.my_pokemon_name.lower():
                battle_state.peer_hp = their_hp
            else:
                battle_state.my_hp = their_hp

            # Send manual ACK for resolution
            ack = make_ack(int(msg.get("sequence_number", "0") or 0))
            node_ref.reliability.sock.sendto(serialize_message(ack), addr)
            print("[RESOLUTION] State updated from peer.")

        elif mtype == "GAME_OVER":
            print(f"[GAME OVER] Winner: {msg.get('winner')}")

        elif mtype == "CHAT_MESSAGE":
            sender = msg.get("sender_name", "Anon")
            if msg.get("content_type") == "TEXT":
                print(f"[CHAT] {sender}: {msg.get('message_text')}")
            else:
                print(f"[CHAT] {sender} sent a sticker.")

    return handler