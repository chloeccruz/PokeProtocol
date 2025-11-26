# network.py
# responsible for UDP socket handling, parsing/serializing messages,
# dispatching incoming messages to the handler (battle logic)

import socket
import threading
import time
from typing import Dict, Tuple, Any
from reliability import ReliabilityLayer
from messages import serialize_message, parse_message, make_ack

BUFFER_SIZE = 65507  # safe UDP payload limit

class PeerNode:
    """
    (high-level networking node) it owns a UDP socket, a ReliabilityLayer,
    and enqueues parsed messages for a handler function to consume
    """

    def __init__(self, bind_ip: str, bind_port: int, handler_fn, verbose=False):
        """
        handler_fn(msg_dict, addr, node)
        """
        self.bind_ip = bind_ip
        self.bind_port = bind_port
        self.handler_fn = handler_fn
        self.verbose = verbose

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((bind_ip, bind_port))
        self.sock.setblocking(False)

        # peer address (set after handshake) can be a single tuple. For spectators / host you may
        # extend this to a list.
        self.peer_addr = None

        self.reliability = ReliabilityLayer(self.sock, verbose=verbose)
        self.running = True

        # threads
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

    def send(self, msg_dict: Dict[str, Any], addr: Tuple[str,int]=None):
        """
        sends msg_dict to addr via reliability layer
        if addr is None, uses self.peer_addr
        """
        if addr is None:
            addr = self.peer_addr
        if addr is None:
            raise RuntimeError("No destination address specified")
        self.reliability.send_with_reliability(msg_dict, addr)
        self.log("Sent", msg_dict.get("message_type"), "to", addr)

    def _recv_loop(self):
        """
        receives UDP datagrams, parses messages, sends ACKs for messages with sequence_number,
        and dispatches to handler_fn.
        """
        while self.running:
            try:
                data, addr = self.sock.recvfrom(BUFFER_SIZE)
            except BlockingIOError:
                time.sleep(0.01)
                continue
            except Exception as e:
                print("[NETWORK] recv error:", e)
                time.sleep(0.1)
                continue

            msg = parse_message(data)
            mtype = msg.get("message_type")
            seq = int(msg.get("sequence_number", "0") or 0)

            # Immediate ACK for messages with seq (non-ACKs)
            if mtype != "ACK" and seq:
                ack = make_ack(seq)
                try:
                    # ACKs are not sent through ReliabilityLayer per spec (they are thin)
                    self.sock.sendto(serialize_message(ack), addr)
                    self.log("Sent ACK", seq, "to", addr)
                except Exception as e:
                    print("[NETWORK] failed to send ACK:", e)

            # Reliability layer should be told when an ACK is received
            if mtype == "ACK":
                ack_num = int(msg.get("ack_number", "0") or 0)
                if ack_num:
                    self.reliability.received_ack(ack_num)
                    self.log("Received ACK", ack_num, "from", addr)
                continue

            # If we don't have a peer_addr yet, set it for this simple implementation
            if self.peer_addr is None and mtype in ("HANDSHAKE_REQUEST", "SPECTATOR_REQUEST", "HANDSHAKE_RESPONSE"):
                self.peer_addr = addr
                self.log("Peer address set to", addr)

            # Dispatch to handler (battle logic), run in a thread to avoid blocking recv
            t = threading.Thread(target=self.handler_fn, args=(msg, addr, self), daemon=True)
            t.start()
