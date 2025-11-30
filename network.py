# network.py

import socket
import threading
import time
from typing import Dict, Tuple, Any
from reliability import ReliabilityLayer
from messages import serialize_message, parse_message, make_ack

BUFFER_SIZE = 65507


class PeerNode:
    def __init__(self, bind_ip: str, bind_port: int, handler_fn, verbose=False):
        self.bind_ip = bind_ip
        self.bind_port = bind_port
        self.handler_fn = handler_fn
        self.verbose = verbose

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((bind_ip, bind_port))
        self.sock.setblocking(False)

        self.peer_addr = None
        self.reliability = ReliabilityLayer(self.sock, verbose=verbose)
        self.running = True

        self.processed_seqs = set()

        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

    def log(self, *args):
        if self.verbose:
            print("[NETWORK]", *args)

    def shutdown(self):
        self.running = False
        try:
            self.reliability.shutdown()
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass

    def send(self, msg_dict: Dict[str, Any], addr: Tuple[str, int] = None):
        if addr is None:
            addr = self.peer_addr
        if addr is None:
            raise RuntimeError("No destination address specified")
        self.reliability.send_with_reliability(msg_dict, addr)
        self.log("Sent", msg_dict.get("message_type"), "to", addr)

    def _recv_loop(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(BUFFER_SIZE)
            except BlockingIOError:
                time.sleep(0.01)
                continue
            except Exception as e:
                if getattr(e, 'winerror', 0) == 10054:
                    continue
                print("[NETWORK] recv error:", e)
                time.sleep(0.1)
                continue

            msg = parse_message(data)

            if not msg or not msg.get("message_type"):
                continue
            mtype = msg.get("message_type")

            try:
                seq = int(msg.get("sequence_number", "0") or 0)
            except ValueError:
                seq = 0

            if mtype == "ACK":
                try:
                    ack_num = int(msg.get("ack_number", "0") or 0)
                    if ack_num:
                        self.reliability.received_ack(ack_num)
                        self.log("Received ACK", ack_num, "from", addr)
                except ValueError:
                    pass
                continue

            if seq > 0:
                ack = make_ack(seq)
                try:
                    self.sock.sendto(serialize_message(ack), addr)
                    self.log("Sent ACK", seq, "to", addr)
                except Exception as e:
                    print("[NETWORK] failed to send ACK:", e)

                if seq in self.processed_seqs:
                    self.log(f"Duplicate packet {seq} detected. Dropping payload.")
                    continue

                self.processed_seqs.add(seq)

            if self.peer_addr is None and mtype in ("HANDSHAKE_REQUEST", "SPECTATOR_REQUEST", "HANDSHAKE_RESPONSE"):
                self.peer_addr = addr
                self.log("Peer address set to", addr)

            t = threading.Thread(target=self.handler_fn, args=(msg, addr, self), daemon=True)
            t.start()