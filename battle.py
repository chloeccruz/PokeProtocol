# battle.py
# implements BattleState, damage calculation (per spec), and handlers for message types
# uses network.PeerNode to send messages.

import threading
import time
import ast
from typing import Dict, Any
from pokemon import get_pokemon
from messages import make_ack, serialize_message

# damage calculation function
def compute_damage(attacker_stat: float, defender_stat: float, base_power: float,
                   type_effectiveness: float = 1.0, boost_multiplier: float = 1.0, level: int = 50) -> int:
    """
    damage formula computed step-by-step:
    damage = (((2 * level / 5 + 2) * base_power * (AttackerStat / DefenderStat)) / 50 + 2) * type_effectiveness * boost_multiplier
    returns integer damage >= 1.
    """
    # Step-by-step to avoid arithmetic mistakes
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
    if damage_int < 1:
        damage_int = 1
    return damage_int

class BattleState:
    """
    maintains HP, stats, turn ownership, and performs action handlers.
    """

    def __init__(self, my_name: str, my_pokemon_name: str, my_pokemon: Dict,
                 peer_name: str=None, peer_pokemon_name: str=None, peer_pokemon: Dict=None):
        self.lock = threading.Lock()
        self.my_name = my_name
        self.my_pokemon_name = my_pokemon_name
        self.peer_name = peer_name or "Peer"
        self.peer_pokemon_name = peer_pokemon_name
        self.my_pokemon = dict(my_pokemon) if my_pokemon else {}
        self.peer_pokemon = dict(peer_pokemon) if peer_pokemon else {}
        self.my_hp = self.my_pokemon.get("hp", 100)
        self.peer_hp = self.peer_pokemon.get("hp", 100)
        self.turn_owner_is_me = False  # Host will set to True when game begins
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

# Handler factory: returns a function suitable for network.PeerNode.handler_fn
def make_handler(battle_state: BattleState, pokemon_db, node, role="joiner", verbose=False):
    """
    battle_state: BattleState object (may be partially filled at setup time)
    node: network.PeerNode
    role: "host"|"joiner"|"spectator"
    """
    # A tiny move database (expandable)
    move_db = {
        "tackle": {"base_power": 40, "damage_category": "physical", "type": "normal"},
        "scratch": {"base_power": 40, "damage_category": "physical", "type": "normal"},
        "thunderbolt": {"base_power": 90, "damage_category": "special", "type": "electric"},
        "flamethrower": {"base_power": 90, "damage_category": "special", "type": "fire"},
    }

    def lookup_move(name):
        return move_db.get(name.lower(), {"base_power": 50, "damage_category": "physical", "type": "normal"})

    # For deterministic RNG operations use seed from handshake value if needed in your implementation

    def handler(msg: Dict[str, str], addr, node_ref):
        mtype = msg.get("message_type")
        if verbose:
            print("[HANDLER] Received", mtype, "from", addr, "msg:", msg)

        # HANDSHAKE
        if mtype == "HANDSHAKE_REQUEST":
            if role == "host":
                # send HANDSHAKE_RESPONSE with seed
                seed = int(time.time()) & 0x7fffffff
                resp = {"message_type": "HANDSHAKE_RESPONSE", "seed": seed}
                node_ref.send(resp, addr)
                print("[HANDSHAKE] Sent HANDSHAKE_RESPONSE with seed", seed)
            else:
                if verbose:
                    print("[HANDSHAKE] Ignoring request (not host).")

        elif mtype == "HANDSHAKE_RESPONSE":
            # joiner receives seed
            if role == "joiner":
                try:
                    seed = int(msg.get("seed", "0"))
                    print("[HANDSHAKE] Received seed", seed)
                except Exception:
                    pass

        elif mtype == "SPECTATOR_REQUEST":
            # Host may accept spectators. Minimal implementation: send a HANDSHAKE_RESPONSE back.
            if role == "host":
                resp = {"message_type": "HANDSHAKE_RESPONSE", "seed": int(time.time()) & 0x7fffffff}
                node_ref.send(resp, addr)
                print("[SPECTATOR] Accepted spectator", addr)

        elif mtype == "BATTLE_SETUP":
            # parse stat_boosts if present (it's a repr(dict) in CSV)
            raw_boosts = msg.get("stat_boosts")
            if raw_boosts:
                try:
                    boosts = ast.literal_eval(raw_boosts)
                except Exception:
                    boosts = {}
            else:
                boosts = {}
            pokemon_name = msg.get("pokemon_name")
            p = get_pokemon(pokemon_db, pokemon_name)
            if p is None:
                print("[SETUP] Unknown pokemon:", pokemon_name)
                p = {"hp": 100, "attack":50, "defense":50, "sp_attack":50, "sp_defense":50, "type1":"", "type2":""}
            # set peer info
            battle_state.peer_pokemon_name = pokemon_name
            battle_state.peer_pokemon = p
            battle_state.peer_hp = p.get("hp", 100)
            battle_state.stat_boosts.update(boosts or {})
            print("[SETUP] Peer chose", pokemon_name)

        elif mtype == "ATTACK_ANNOUNCE":
            # Defender acknowledges and sends DEFENSE_ANNOUNCE
            move = msg.get("move_name", "tackle")
            seq = int(msg.get("sequence_number", "0") or 0)
            print("[TURN] Attack announced:", move)
            # Respond with DEFENSE_ANNOUNCE
            resp = {"message_type": "DEFENSE_ANNOUNCE"}
            node_ref.send(resp, addr)

            # Store last incoming attack to be evaluated in CALCULATION_REPORT step
            node_ref._last_incoming_attack = {"move_name": move, "sequence": seq}

        elif mtype == "DEFENSE_ANNOUNCE":
            # Attacker receives DEFENSE_ANNOUNCE: compute damage from attacker perspective and send CALCULATION_REPORT
            print("[TURN] DEFENSE_ANNOUNCE received — compute and send CALCULATION_REPORT")
            # Check we have last announced move stored
            last_my = getattr(node_ref, "_my_last_announced_move", {"move_name":"tackle"})
            moveinfo = lookup_move(last_my["move_name"])
            # select attack/def stats
            if moveinfo["damage_category"] == "physical":
                atk_stat = battle_state.my_pokemon.get("attack", 50)
                def_stat = battle_state.peer_pokemon.get("defense", 50)
            else:
                atk_stat = battle_state.my_pokemon.get("sp_attack", 50)
                def_stat = battle_state.peer_pokemon.get("sp_defense", 50)

            dmg = compute_damage(attacker_stat=atk_stat, defender_stat=def_stat, base_power=moveinfo["base_power"])
            # locally apply
            battle_state.apply_damage_to_peer(dmg)

            report = {
                "message_type": "CALCULATION_REPORT",
                "attacker": battle_state.my_pokemon_name,
                "move_used": last_my["move_name"],
                "remaining_health": battle_state.my_hp,
                "damage_dealt": dmg,
                "defender_hp_remaining": battle_state.peer_hp,
                "status_message": f"{battle_state.my_pokemon_name} used {last_my['move_name']}!",
            }
            node_ref.send(report, addr)

        elif mtype == "CALCULATION_REPORT":
            # Compare peer's report with our local calculation
            print("[TURN] Received CALCULATION_REPORT:", msg.get("status_message"))
            attacker = msg.get("attacker", "")
            move_name = msg.get("move_used", "tackle")
            moveinfo = lookup_move(move_name)

            if attacker.lower() == battle_state.peer_pokemon_name.lower():
                # Peer attacked us. Compute expected damage to apply
                if moveinfo["damage_category"] == "physical":
                    atk = battle_state.peer_pokemon.get("attack", 50)
                    dfn = battle_state.my_pokemon.get("defense", 50)
                else:
                    atk = battle_state.peer_pokemon.get("sp_attack", 50)
                    dfn = battle_state.my_pokemon.get("sp_defense", 50)
                local_damage = compute_damage(atk, dfn, moveinfo["base_power"])
                reported = int(msg.get("damage_dealt", "0") or 0)
                if local_damage == reported:
                    # apply and confirm
                    battle_state.apply_damage_to_me(local_damage)
                    conf = {"message_type": "CALCULATION_CONFIRM"}
                    node_ref.send(conf, addr)
                    print("[TURN] Calculation matched. Sent CALCULATION_CONFIRM.")
                else:
                    # discrepancy - initiate resolution
                    rr = {
                        "message_type": "RESOLUTION_REQUEST",
                        "attacker": attacker,
                        "move_used": move_name,
                        "damage_dealt": local_damage,
                        "defender_hp_remaining": battle_state.my_hp
                    }
                    node_ref.send(rr, addr)
                    print("[TURN] Discrepancy detected (reported:", reported, "local:", local_damage, "). Sent RESOLUTION_REQUEST")
            else:
                # We attacked; compare defender_hp_remaining
                reported_def_hp = int(msg.get("defender_hp_remaining", "0") or 0)
                if reported_def_hp == battle_state.peer_hp:
                    conf = {"message_type": "CALCULATION_CONFIRM"}
                    node_ref.send(conf, addr)
                    print("[TURN] Calculation match for our attack. Sent CALCULATION_CONFIRM.")
                else:
                    rr = {
                        "message_type": "RESOLUTION_REQUEST",
                        "attacker": attacker,
                        "move_used": move_name,
                        "damage_dealt": int(msg.get("damage_dealt", "0") or 0),
                        "defender_hp_remaining": battle_state.peer_hp
                    }
                    node_ref.send(rr, addr)
                    print("[TURN] Discrepancy for our attack; sent RESOLUTION_REQUEST.")

        elif mtype == "CALCULATION_CONFIRM":
            # Turn confirmed: reverse turn owner
            battle_state.turn_owner_is_me = not battle_state.turn_owner_is_me
            print("[TURN] CALCULATION_CONFIRM: turn toggled; now turn_owner_is_me =", battle_state.turn_owner_is_me)
            # Check for game over
            over, result = battle_state.is_over()
            if over:
                winner, loser = result
                go = {"message_type": "GAME_OVER", "winner": winner, "loser": loser}
                node_ref.send(go, addr)
                print("[GAME_OVER] Sent GAME_OVER", go)

        elif mtype == "RESOLUTION_REQUEST":
            # For simplicity accept peer's resolution and ACK back
            their_hp = int(msg.get("defender_hp_remaining", "0") or 0)
            attacker = msg.get("attacker", "")
            if attacker.lower() == battle_state.my_pokemon_name.lower():
                # they say we attacked; their defender_hp refers to peer
                battle_state.peer_hp = their_hp
            else:
                battle_state.my_hp = their_hp
            # ACK the resolution request sequence number if present
            seq = int(msg.get("sequence_number", "0") or 0)
            ack = make_ack(seq)
            # ACK must be sent (here through node.send which uses reliability for non-ACKs; we will send direct)
            # To be consistent, use node.send (it will add sequence_number) — but the spec said ACKs don't use sequence.
            node_ref.reliability.sock.sendto(serialize_message(ack), addr)
            print("[RESOLUTION] Accepted peer values and sent ACK.")

        elif mtype == "GAME_OVER":
            winner = msg.get("winner")
            loser = msg.get("loser")
            print(f"[GAME_OVER] Received — Winner: {winner} | Loser: {loser}")

        elif mtype == "CHAT_MESSAGE":
            sender = msg.get("sender_name", "Anon")
            ctype = msg.get("content_type", "TEXT")
            if ctype == "TEXT":
                print(f"[CHAT][{sender}] {msg.get('message_text','')}")
            elif ctype == "STICKER":
                # server already decoded? We store sticker handling in CLI layer.
                print(f"[CHAT] Received sticker from {sender} (sequence {msg.get('sequence_number')})")

        else:
            print("[HANDLER] Unknown message type", mtype)

    return handler
