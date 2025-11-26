# main.py
# basic CLI to run host/joiner/spectator roles

import argparse
import time
import base64
import os
from pokemon import load_csv, get_pokemon
from network import PeerNode
from battle import BattleState, make_handler

def run(args):
    pokemon_db = load_csv(args.pokemon_csv)
    # simple prompt gather
    my_name = args.name
    # create an initial, possibly empty BattleState; will be filled when setup messages arrive
    my_pokemon = get_pokemon(pokemon_db, args.pokemon) if args.pokemon else None
    state = BattleState(my_name=my_name,
                       my_pokemon_name=args.pokemon or "",
                       my_pokemon=my_pokemon or {})

    # create network node with handler from battle module
    # handler needs node ref; we create with placeholder and set node after creation
    node = PeerNode(bind_ip=args.bind_ip, bind_port=args.port,
                    handler_fn=lambda msg,addr,node_ref: None,
                    verbose=args.verbose)

    # now build handler and replace
    handler = make_handler(state, pokemon_db, node, role=args.role, verbose=args.verbose)
    node.handler_fn = handler

    # if joiner or spectator, set peer address and do handshake
    if args.role in ("joiner", "spectator"):
        if not args.peer_ip or not args.peer_port:
            print("Peer IP/port required for joiner/spectator")
            return
        node.peer_addr = (args.peer_ip, args.peer_port)
        if args.role == "joiner":
            node.send({"message_type": "HANDSHAKE_REQUEST"})
            print("[MAIN] Sent HANDSHAKE_REQUEST")
        else:
            node.send({"message_type": "SPECTATOR_REQUEST"})
            print("[MAIN] Sent SPECTATOR_REQUEST")
    else:
        print("[MAIN] Running as host, waiting for handshake requests...")

    print("Commands:")
    print("  /setup POKEMONNAME    -> send BATTLE_SETUP")
    print("  /attack MOVENAME      -> ATTACK_ANNOUNCE")
    print("  /chat TEXT            -> send chat text")
    print("  /sticker PATH         -> send sticker (Base64)")
    print("  /status               -> show HPs")
    print("  /quit                 -> exit")

    try:
        while True:
            cmd = input("> ").strip()
            if not cmd:
                continue
            if cmd == "/quit":
                break
            if cmd.startswith("/setup "):
                _, pname = cmd.split(" ", 1)
                node.send({"message_type": "BATTLE_SETUP",
                           "communication_mode": "P2P",
                           "pokemon_name": pname.strip(),
                           "stat_boosts": {"special_attack_uses":5, "special_defense_uses":5}})
                # update our local state
                state.my_pokemon_name = pname.strip()
                state.my_pokemon = get_pokemon(pokemon_db, pname.strip()) or {}
                state.my_hp = state.my_pokemon.get("hp", state.my_hp)
                print("[MAIN] BATTLE_SETUP sent for", pname.strip())
                continue
            if cmd.startswith("/attack "):
                _, move = cmd.split(" ", 1)
                node.send({"message_type": "ATTACK_ANNOUNCE", "move_name": move.strip()})
                # store last announced
                node._my_last_announced_move = {"move_name": move.strip()}
                print("[MAIN] ATTACK_ANNOUNCE sent:", move.strip())
                continue
            if cmd.startswith("/chat "):
                _, text = cmd.split(" ", 1)
                node.send({"message_type": "CHAT_MESSAGE", "sender_name": my_name, "content_type": "TEXT", "message_text": text.strip()})
                continue
            if cmd.startswith("/sticker "):
                _, path = cmd.split(" ",1)
                path = path.strip()
                if not os.path.exists(path):
                    print("Sticker file not found.")
                    continue
                data = open(path, "rb").read()
                b64 = base64.b64encode(data).decode("utf-8")
                node.send({"message_type": "CHAT_MESSAGE", "sender_name": my_name, "content_type": "STICKER", "sticker_data": b64})
                print("Sent sticker.")
                continue
            if cmd == "/status":
                print(f"My HP: {state.my_hp} | Peer HP: {state.peer_hp}")
                continue
            print("Unknown command.")
    finally:
        node.shutdown()
        print("Shutdown complete.")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", choices=["host","joiner","spectator"], required=True)
    ap.add_argument("--bind-ip", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=9999)
    ap.add_argument("--peer-ip", default=None)
    ap.add_argument("--peer-port", type=int, default=None)
    ap.add_argument("--pokemon-csv", default="pokemon_data.csv")
    ap.add_argument("--pokemon", default=None, help="Your Pokémon name to use in setup")
    ap.add_argument("--name", default="Player1")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    run(args)
