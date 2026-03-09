import socket
import sys
import threading

def get_lan_ip():
    """Forces the OS to find the actual LAN IP used for external routing."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't send any data; just opens the interface
        s.connect(('8.8.8.8', 1))
        ip = s.getsockname()[0]
    except Exception:
        # Fallback if no internet access is available
        ip = socket.gethostbyname(socket.gethostname())
    finally:
        s.close()
    return ip

def start_server(name):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    local_ip = get_lan_ip()
    
    # Bind to the discovered LAN IP on an ephemeral port
    sock.bind((local_ip, 0))
    ip, port = sock.getsockname()
    
    print(f"--- UDP Host '{name}' Active ---")
    print(f"Listening on LAN IP: {ip}:{port}")
    print("----------------------------------")

    known_clients = set()

    def handle_incoming():
        while True:
            try:
                data, addr = sock.recvfrom(4096)
                known_clients.add(addr)
                print(f"\n[From {addr}] {data.decode().strip()}")
                print(f"{name} > ", end="", flush=True)
            except Exception as e:
                print(f"Recv Error: {e}")

    threading.Thread(target=handle_incoming, daemon=True).start()

    while True:
        try:
            msg = input(f"{name} > ")
            full_msg = f"{name}:{msg}".encode()
            for client in list(known_clients):
                try:
                    sock.sendto(full_msg, client)
                except:
                    known_clients.remove(client)
        except EOFError:
            break

if __name__ == "__main__":
    start_server(sys.argv[1] if len(sys.argv) > 1 else "Host")