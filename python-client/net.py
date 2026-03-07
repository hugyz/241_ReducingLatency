from __future__ import annotations

import socket
import statistics
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from protocol import MessageType, create_message, decode_message, encode_message

Addr = Tuple[str, int]
Handler = Callable[[Dict, Addr], None]


# RTT measurement result for one endpoint.
@dataclass
class EndpointResult:
    addr: Addr
    rtts_ms: List[float]
    median_ms: float


class UdpTransport:
    """
    UDP transport with:
      - thread-safe seq generator
      - send(msg, addr)
      - background receive loop + dispatch by msg["type"]
      - synchronous request/response helper for ping measurement
    """

    def __init__(self, bind_port: int = 0, recv_buf: int = 65535):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", bind_port))
        self.sock.settimeout(0.2)
        self.recv_buf = recv_buf

        self._seq = 0
        self._seq_lock = threading.Lock()

        self._handlers: Dict[str, List[Handler]] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def next_seq(self) -> int:
        """
        Sequence number used to correlate PING<->PONG and other request/response patterns.
        """
        with self._seq_lock:
            self._seq += 1
            return self._seq

    # handlers
    def on(self, msg_type: str, handler: Handler) -> None:
        """Register a handler for a given message type string (e.g., 'STATE_UPDATE')."""
        self._handlers.setdefault(msg_type, []).append(handler)

    def _dispatch(self, msg: Dict, addr: Addr) -> None:
        """
        Dispatch an inbound message to all handlers for msg["type"].
        Any handler exceptions are swallowed to keep the recv thread alive.
        """
        mtype = msg.get("type", "")
        for h in self._handlers.get(mtype, []):
            try:
                h(msg, addr)
            except Exception:
                # keep recv thread alive even if handler errors
                pass

    def send(self, msg: Dict, addr: Addr) -> None:
        self.sock.sendto(encode_message(msg), addr)

    def recv_once(self) -> Optional[Tuple[Dict, Addr]]:
        try:
            data, addr = self.sock.recvfrom(self.recv_buf)
        except socket.timeout:
            return None
        msg = decode_message(data)
        return msg, addr

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()

    def _recv_loop(self) -> None:
        """
        Background receive loop:
        - read UDP packets
        - decode JSON
        - dispatch to handlers by message type
        """
        while self._running:
            item = self.recv_once()
            if not item:
                continue
            msg, addr = item
            self._dispatch(msg, addr)

    def close(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        try:
            self.sock.close()
        except OSError:
            pass


def ping_endpoint(
    transport: UdpTransport,
    addr: Addr,
    client_id: str,
    n: int = 10,
    timeout_s: float = 0.25,
    gap_s: float = 0.03,
) -> EndpointResult:
    """
    synchronous ping test:
    - sends N PINGs and waits for matching PONG seq
    - temporarily change socket timeout for ping.
    """ 
    rtts: List[float] = []

    old_timeout = transport.sock.gettimeout()
    transport.sock.settimeout(timeout_s)

    for _ in range(n):
        seq = transport.next_seq()
        msg = create_message(MessageType.PING.value, client_id, seq, payload={})
        t0 = time.time()
        transport.send(msg, addr)

        try:
            data, _ = transport.sock.recvfrom(65535)
            pong = decode_message(data)
            if pong.get("type") == MessageType.PONG.value and pong.get("seq") == seq:
                rtts.append((time.time() - t0) * 1000.0)
        except socket.timeout:
            pass

        time.sleep(gap_s)

    transport.sock.settimeout(old_timeout)

    median_ms = statistics.median(rtts) if rtts else float("inf")
    return EndpointResult(addr=addr, rtts_ms=rtts, median_ms=median_ms)

def choose_best_endpoint(
    transport: UdpTransport,
    endpoints: List[Addr],
    client_id: str,
    n: int = 7,
) -> Tuple[EndpointResult, List[EndpointResult]]:
    """
    Returns (best, all_results_sorted_by_latency)
    """
    results = [ping_endpoint(transport, ep, client_id, n=n) for ep in endpoints]
    results.sort(key=lambda r: r.median_ms)
    return results[0], results