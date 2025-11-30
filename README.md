# P2P Pokémon Battle Protocol (PokeProtocol) Implementation

## Overview

This project is a fully functional Peer-to-Peer (P2P) Pokémon battle system built over UDP. It implements a custom **Reliable Data Transfer (RDT)** protocol to handle packet loss, reordering, and duplicate messages, ensuring that the game state remains synchronized between two players even on an unreliable network.

## Features

- **Custom Reliability Layer:** Implements Sequence Numbers, ACKs, and Retransmissions to make UDP reliable.

- **Duplicate Handling:** Detects and drops duplicate packets (preventing double damage bugs) while ensuring ACKs are resent.

- **Game State Synchronization:** Uses a 4-step turn protocol (```ATTACK```  -> ```DEFENSE```  -> ```CALCULATION``` -> ```CONFIRM``` ) to verify damage on both sides.

- **Discrepancy Resolution:** Automatically detects if peers calculate different damage values and triggers a resolution request.

- **Chat & Stickers:** Supports real-time text chat and Base64-encoded image stickers.

- **Architecture:** Modular design separating Networking, Game Logic, and UI.

## File Structure

- ```**main.py:**``` The entry point. Handles CLI user input and starts the node.

- ```**network.py:**``` Manages the UDP socket, threading, and packet dispatching.

- ```**reliability.py:**``` Handles the "Stop-and-Wait" logic, retransmission timers, and tracking pending ACKs.

- ```**battle.py:**``` Contains the ```BattleState```, turn logic, and the specific damage formulas.

- ```**messages.py:**``` Utilities for serializing/parsing the ```key: value``` message format.

- ```**pokemon.py:**``` Handles CSV parsing and stats lookup.

## How to Run

**Prerequisites**

- Python 3.x

- ```pokemon_data.csv``` (Must be in the same folder)

**1. Start the Host**

Open a terminal and run:
``` 
python main.py --role host --name Chloe --pokemon Pikachu --port 9999
``` 
(change the host name and pokemon as you wish)

**2. Start the Joiner**

Open a second terminal and run:
``` 
python main.py --role joiner --name Isabelle --pokemon Charmander --port 10000 --peer-ip 127.0.0.1 --peer-port 9999
``` 
(change the joiner  name and pokemon as you wish)

## In-Game Commands

Once connected, use these commands in the terminal:

- ```/setup [PokemonName]```

  - _Example:_ ```/setup Squirtle```

  - _Description:_ Locks in your Pokémon and sends stats to the peer. Both players must do this to start.

- ```/attack [MoveName]```

  - _Example:_ ```/attack Water Gun```

  - _Description:_ Initiates an attack turn.

- ```/chat [Message]```

  - _Example:_ ```/chat Good luck!```

  - _Description:_ Sends a text message.

- ```/sticker [FilePath]```

  - _Example:_ ```/sticker image.png```

  - _Description:_ Sends an image file as a sticker.

- ```/status```

  - Description: Displays current HP for both players.

- ```/quit```

  - Description: Disconnects and closes the game.

## Architecture & Logic

**The Reliability Layer**

Since UDP is unreliable, ```ReliabilityLayer``` is built (in ```reliability.py```). It works by:

1. Assigning a strictly increasing ```sequence_number``` to every critical message.

2. Storing sent messages in a ```pending``` dictionary.

3. A background thread checks if a message has been in ```pending longer``` than 0.5s. If so, it retransmits.

4. When an ACK is received, the message is removed from ```pending```.

**Turn Logic & Sync**

To prevent cheating, damage is calculated locally by both parties:

1. **Attacker** sends ```ATTACK_ANNOUNCE```.

2. **Defender** receives it and sends ```DEFENSE_ANNOUNCE```.

3. **Attacker** calculates damage (using Type Effectiveness from CSV) and sends ```CALCULATION_REPORT```.

4. **Defender** compares that report with their own local calculation.

  - If they match -> Send ```CALCULATION_CONFIRM```.

  - If they mismatch -> ```Send RESOLUTION_REQUEST```.

## AI Usage Disclaimer

Per the course policy, AI tools (ChatGPT and Gemini) were used to assist in the development of this project.

**Code Generation:** Used to generate the boilerplate for the CSV parsing regex and the base structure of the threaded socket listener.

**Debugging:** Used to troubleshoot ```BlockingIOError``` issues with the UDP socket and to refine the duplicate packet handling logic.

**Refining:** AI was used to help write the docstrings and clean up the ```BattleState``` class structure.

**Verification:** All AI-generated code was manually reviewed, tested, and modified by the group to ensure it adheres to the specific message serialization requirements of the protocol.
