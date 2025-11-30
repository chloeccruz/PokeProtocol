# network.py
# Low-level networking. Manages the UDP socket, parses incoming bytes,
# and dispatches messages to the Battle logic.

import socket
import threading
import time
from typing import Dict, Tuple, Any
from reliability import ReliabilityLayer
from messages import serialize_message, parse_message, make_ack

BUFFER_SIZE = 65507  # Max UDP size


class PeerNode:
    def __init__(self, bind_ip: str, bind_port: int, handler_fn, verbose=False):
        self.bind_ip = bind_ip
        self.bind_port = bind_port
        self.handler_fn = handler_fn
        self.verbose = verbose

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # --- FIX: INCREASE BUFFER SIZE FOR STICKERS ---
        # Sets send/receive buffer to 64KB to handle larger images on localhost
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
        except Exception:
            pass  # Some OS might not support this, ignore if so
        # --------------------------------------------------

        self.sock.bind((bind_ip, bind_port))

        # Set to non-blocking so we don't freeze if no data comes
        self.sock.setblocking(False)

        self.peer_addr = None
        self.reliability = ReliabilityLayer(self.sock, verbose=verbose)
        self.running = True

        # Keep track of sequence numbers we've seen to avoid processing duplicates
        self.processed_seqs = set()

        # Start listening in a background thread
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

    def shutdown(self):
        self.running = False
        try:
            self.reliability.shutdown()
        except:
            pass
        try:
            self.sock.close()
        except:
            pass

    def send(self, msg_dict: Dict[str, Any], addr: Tuple[str, int] = None):
        if addr is None:
            addr = self.peer_addr
        if addr is None:
            print("Error: No address to send to.")
            return
        # Pass through reliability layer to handle retransmissions
        self.reliability.send_with_reliability(msg_dict, addr)

    def _recv_loop(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(BUFFER_SIZE)
            except BlockingIOError:
                # No data ready, sleep briefly to save CPU power
                time.sleep(0.01)
                continue
            except Exception as e:
                # Windows connection reset error check
                if getattr(e, 'winerror', 0) == 10054:
                    continue
                print(f"[NET] Recv error: {e}")
                time.sleep(0.1)
                continue

            msg = parse_message(data)

            # Ignore empty/ghost packets
            if not msg or not msg.get("message_type"):
                continue

            mtype = msg.get("message_type")

            # Safe int conversion
            try:
                seq = int(msg.get("sequence_number", "0") or 0)
            except ValueError:
                seq = 0

            # --- ACK Handling ---
            if mtype == "ACK":
                try:
                    ack_num = int(msg.get("ack_number", "0") or 0)
                    if ack_num:
                        self.reliability.received_ack(ack_num)
                except:
                    pass
                continue

            # --- Normal Message Handling ---
            if seq > 0:
                # Always send an ACK immediately so the sender stops retransmitting
                ack = make_ack(seq)
                try:
                    self.sock.sendto(serialize_message(ack), addr)
                except Exception as e:
                    print(f"[NET] ACK send failed: {e}")

                # Check if we already processed this packet (Duplicate Check)
                if seq in self.processed_seqs:
                    if self.verbose:
                        print(f"[NET] Ignoring duplicate seq {seq}")
                    continue

                # Mark as seen
                self.processed_seqs.add(seq)

            # Auto-set peer address on first contact
            if self.peer_addr is None and mtype in ("HANDSHAKE_REQUEST", "SPECTATOR_REQUEST", "HANDSHAKE_RESPONSE"):
                self.peer_addr = addr

            # Run game logic in a thread so we don't block the network listener
            t = threading.Thread(target=self.handler_fn, args=(msg, addr, self), daemon=True)
            t.start()