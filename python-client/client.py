from __future__ import annotations

import argparse
import random
import threading
import time
from typing import List, Tuple

from net import UdpTransport, choose_best_endpoint
from protocol import MessageType, create_message, decode_message

Addr = Tuple[str, int]


def parse_addr(s: str) -> Addr:
    host, port = s.strip().split(":")
    return host, int(port)


class Client:
    def __init__(self, client_id: str, main_server: Addr):
        self.client_id = client_id
        self.main_server = main_server
        self.tick_rate = 30 # current tick rate default 30 ticks per second

        self.transport = UdpTransport(bind_port=0)
        self.server: Addr | None = None  # chosen edge

        self._running = False
        self._send_thread: threading.Thread | None = None

        # local predicted state for demo
        self.tick = 0
        self.x = 0.0
        self.y = 0.0

        # handlers for incoming server messages (for later integration)
        self.transport.on(MessageType.PREDICTION.value, self.on_prediction)
        # do later if needed
        # self.transport.on(MessageType.STATE_UPDATE.value, self.on_state_update)
        self.transport.on(MessageType.ROLLBACK.value, self.on_rollback)
       
    # Simulated EDGE_LIST (delete when integrated with go server)
    def discover_edges_dummy(self) -> list[Addr]:
        dummy_edge_list_msg = {
            "type": MessageType.EDGE_LIST.value,
            "client_id": self.client_id,
            "seq": 1,
            "timestamp_ms": int(time.time() * 1000),
            "payload": {
                "edges": [
                    {"host": "127.0.0.1", "port": 9000},
                    {"host": "127.0.0.1", "port": 9001},
                ],
                "ttl_ms": 10_000,
            },
        }

        edges = dummy_edge_list_msg["payload"]["edges"]
        return [(e["host"], int(e["port"])) for e in edges]

    # send DISCOVER to main server, wait for EDGE_LIST. Retries because UDP can drop.
    def discover_edges(self, timeout_s: float = 0.25, attempts: int = 3) -> List[Addr]:
        old_timeout = self.transport.sock.gettimeout()
        self.transport.sock.settimeout(timeout_s)

        try:
            for _ in range(attempts):
                seq = self.transport.next_seq()
                discover = create_message(
                    MessageType.DISCOVER.value,
                    self.client_id,
                    seq,
                    payload={},
                )
                self.transport.send(discover, self.main_server)

                try:
                    data, _addr = self.transport.sock.recvfrom(65535)
                    msg = decode_message(data)

                    if msg.get("type") == MessageType.EDGE_LIST.value and msg.get("seq") == seq:
                        edges = msg.get("payload", {}).get("edges", [])
                        out: List[Addr] = []
                        for e in edges:
                            if isinstance(e, dict) and "host" in e and "port" in e:
                                out.append((str(e["host"]), int(e["port"])))
                        return out
                except Exception:
                    # timeout or parse error: retry
                    pass

            raise RuntimeError("DISCOVER failed: no EDGE_LIST received")
        finally:
            self.transport.sock.settimeout(old_timeout)

    # pick best endpoint with lowest median RTT
    def select_best_edge(self, edges: List[Addr]) -> Addr:
        best, all_results = choose_best_endpoint(self.transport, edges, self.client_id, n=7)

        print("[client] ping results:")
        for r in all_results:
            print(f"  {r.addr} rtts={r.rtts_ms} median={r.median_ms:.2f}ms")

        print(f"[client] selected edge {best.addr} (median={best.median_ms:.2f}ms)")
        return best.addr

    # register with best endpoint
    def register_with_edge(self) -> None:
        assert self.server is not None

        seq = self.transport.next_seq()
        reg = create_message(
            MessageType.REGISTER.value,
            self.client_id,
            seq,
            payload={
                "chosen_edge": f"{self.server[0]}:{self.server[1]}",
            },
        )
        self.transport.send(reg, self.server)

    # start loops
    def start_prediction_loop(self) -> None:
        """
        Start:
          - UDP receive thread (dispatch)
          - client send thread (prediction updates)
        """
        self.transport.start()
        self._running = True
        self._send_thread = threading.Thread(target=self._send_loop, daemon=True)
        self._send_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._send_thread:
            self._send_thread.join(timeout=1.0)
        self.transport.close()


    def run(self, use_discovery: bool = False) -> None:
        """
        Main client flow:
          1. discover edges (dummy or real)
          2. choose best via ping
          3. register
          4. start send/recv loops
        """
        if use_discovery:
            edges = self.discover_edges()
            print(f"[client] discovered edges from main {self.main_server}: {edges}")
        else:
            edges = self.discover_edges_dummy()
            print(f"[client] discovered edges (dummy): {edges}")

        if not edges:
            raise RuntimeError("No edges available")

        self.server = self.select_best_edge(edges)
        self.register_with_edge()
        self.start_prediction_loop()

    # send prediction updates
    def _send_loop(self) -> None:
        period = 1.0 / self.tick_rate
        next_t = time.perf_counter()

        while self._running:
            now = time.perf_counter()
            if now < next_t:
                time.sleep(next_t - now)
            next_t += period

            # random walk position updates
            dx = random.choice([-1, 0, 1])
            dy = random.choice([-1, 0, 1])
            speed = 0.1

            self.x += dx * speed
            self.y += dy * speed
            self.tick += 1

            seq = self.transport.next_seq()
            pred = create_message(
                MessageType.PREDICTION.value,
                self.client_id,
                seq,
                payload={
                    "tick": self.tick,
                    "state": {"x": self.x, "y": self.y},
                    "input": {"dx": dx, "dy": dy},
                },
            )

            assert self.server is not None
            self.transport.send(pred, self.server)

    # incoming handlers
    def on_prediction(self, msg: dict, addr: Addr) -> None:
        now_ms = int(time.time() * 1000)

        payload = msg.get("payload", {})

        source_id = msg.get("client_id")
        send_ts = msg.get("timestamp_ms")

        if source_id is None or send_ts is None:
            return
        if source_id == self.client_id:
            return

        latency_ms = now_ms - send_ts

        print(
            f"[client] FORWARDED_UPDATE source={source_id} "
            f"dest={self.client_id} latency_ms={latency_ms}" # type: ignore
        )
    
    def on_rollback(self, msg: dict, addr: Addr) -> None:
        print(f"[client] ROLLBACK from {addr}: {msg}")
        auth = msg.get("payload", {}).get("authoritative")
        if isinstance(auth, dict):
            self.x = float(auth.get("x", self.x))
            self.y = float(auth.get("y", self.y))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-id", default="c1")
    ap.add_argument("--main", default="127.0.0.1:8000", help="main server host:port for discovery")
    ap.add_argument( # remove later
        "--use-discovery",
        action="store_true",
        help="Use real DISCOVER/EDGE_LIST from main server (instead of dummy list).",
    )
    args = ap.parse_args()

    c = Client(args.client_id, parse_addr(args.main))
    c.run(use_discovery=args.use_discovery)

    print("[client] running. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[client] stopping...")
        c.stop()


if __name__ == "__main__":
    main()