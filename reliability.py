# reliability.py

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Tuple, Any
from messages import serialize_message

RETRANSMISSION_TIMEOUT = 0.5
MAX_RETRIES = 3

@dataclass
class PendingMessage:
    payload: bytes
    dest: Tuple[str,int]
    seq: int
    last_sent: float
    retries: int = 0
    msg_dict: Dict[str,Any] = field(default_factory=dict)

class ReliabilityLayer:
    def __init__(self, sock, verbose=False, timeout=RETRANSMISSION_TIMEOUT, max_retries=MAX_RETRIES):
        self.sock = sock
        self.verbose = verbose
        self.timeout = timeout
        self.max_retries = max_retries

        self.lock = threading.Lock()
        self.pending: Dict[int, PendingMessage] = {}
        self.next_seq = 1

        self.running = True
        self._thread = threading.Thread(target=self._checker, daemon=True)
        self._thread.start()

    def log(self, *a):
        if self.verbose:
            print("[RELIABILITY]", *a)

    def next_sequence(self) -> int:
        with self.lock:
            s = self.next_seq
            self.next_seq += 1
            return s

    def send_with_reliability(self, msg_dict: Dict[str,Any], dest: Tuple[str,int]):
        if msg_dict.get("message_type") != "ACK":
            if "sequence_number" not in msg_dict:
                msg_dict["sequence_number"] = self.next_sequence()
        payload = serialize_message(msg_dict)
        seq = int(msg_dict.get("sequence_number", 0) or 0)

        try:
            self.sock.sendto(payload, dest)
            self.log("Sent seq", seq, "to", dest, "type", msg_dict.get("message_type"))
        except Exception as e:
            print("[RELIABILITY] send failed:", e)

        if seq:
            with self.lock:
                self.pending[seq] = PendingMessage(payload=payload, dest=dest, seq=seq, last_sent=time.time(), msg_dict=dict(msg_dict))

    def received_ack(self, ack_num: int):
        with self.lock:
            if ack_num in self.pending:
                del self.pending[ack_num]
                self.log("Cleared pending seq", ack_num)

    def shutdown(self):
        self.running = False
        self._thread.join(timeout=1.0)

    def _checker(self):
        while self.running:
            time.sleep(0.05)
            now = time.time()
            to_retransmit = []
            timed_out = []
            with self.lock:
                for seq, pm in list(self.pending.items()):
                    if now - pm.last_sent >= self.timeout:
                        if pm.retries < self.max_retries:
                            pm.retries += 1
                            pm.last_sent = now
                            to_retransmit.append(pm)
                            self.log("Retransmit seq", seq, "retry", pm.retries)
                        else:
                            timed_out.append(seq)
                            print(f"[RELIABILITY] Seq {seq} exceeded max retries; giving up.")
            for pm in to_retransmit:
                try:
                    self.sock.sendto(pm.payload, pm.dest)
                except Exception as e:
                    print("[RELIABILITY] retransmit failed:", e)
            with self.lock:
                for seq in timed_out:
                    if seq in self.pending:
                        del self.pending[seq]
