import socket
import sys
import threading
import time

def start_client(name, server_addr_str):
    try:
        ip, port = server_addr_str.split(":")
        server_addr = (ip, int(port))
    except ValueError:
        print("Error: Address must be in IP:PORT format.")
        return

    # Create socket and bind to an ephemeral port to stay 'alive' for the Edge
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('', 0)) # Bind to any local address and port

    def receive():
        while True:
            try:
                # Buffers the response from the Edge
                data, addr = sock.recvfrom(4096)
                if data:
                    # Clear the current line and print the message
                    # \r returns to start of line, then we print and restore prompt
                    print(f"\r[Received from {addr}] {data.decode().strip()}")
                    print("> ", end="", flush=True)
            except Exception as e:
                print(f"\n[Receiver Error] {e}")
                break

    # Start the background listener
    listener = threading.Thread(target=receive, daemon=True)
    listener.start()

    print(f"--- Client '{name}' Active ---")
    print(f"Targeting Edge: {server_addr_str}")
    print(f"Local Socket: {sock.getsockname()}")
    print("Type messages below. Type 'exit' to quit.")

    while True:
        try:
            msg = input("> ")
            if msg.lower() == "exit": 
                break
            if not msg:
                continue
                
            payload = f"{name}:{msg}".encode()
            sock.sendto(payload, server_addr)
        except EOFError:
            break
        except Exception as e:
            print(f"Send Error: {e}")

    sock.close()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python client.py <name> <edge_ip:port>")
    else:
        start_client(sys.argv[1], sys.argv[2])