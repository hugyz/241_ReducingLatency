package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net"
	"os"
	"strconv"
	"sync"
	"time"
)

// ─── Protocol types (mirrors python-client/protocol.py) ──────────────────────

type Message struct {
	Type        string         `json:"type"`
	ClientID    string         `json:"client_id"`
	Seq         int            `json:"seq"`
	TimestampMs int64          `json:"timestamp_ms"`
	Payload     map[string]any `json:"payload"`
}

const (
	MsgPing        = "PING"
	MsgPong        = "PONG"
	MsgDiscover    = "DISCOVER"
	MsgEdgeList    = "EDGE_LIST"
	MsgRegister    = "REGISTER"
	MsgPrediction  = "PREDICTION"
	MsgStateUpdate = "STATE_UPDATE"
	MsgRollback    = "ROLLBACK"
)

func nowMs() int64 {
	return time.Now().UnixMilli()
}

func encode(msg Message) ([]byte, error) {
	return json.Marshal(msg)
}

func decode(data []byte) (Message, error) {
	var msg Message
	err := json.Unmarshal(data, &msg)
	return msg, err
}

// ─── Client registry ──────────────────────────────────────────────────────────

type ClientInfo struct {
	addr *net.UDPAddr
	id   string
}

var (
	clientsMu sync.RWMutex
	// key: client_id → ClientInfo
	clientsByID = make(map[string]*ClientInfo)
)

func registerClient(id string, addr *net.UDPAddr) {
	clientsMu.Lock()
	defer clientsMu.Unlock()
	clientsByID[id] = &ClientInfo{addr: addr, id: id}
	fmt.Printf("[edge] registered client %q at %s\n", id, addr)
}

func unregisterClient(id string) {
	clientsMu.Lock()
	defer clientsMu.Unlock()
	delete(clientsByID, id)
}

// broadcast sends data to all registered clients except the sender.
func broadcast(conn *net.UDPConn, senderID string, data []byte, delay time.Duration) {
	clientsMu.RLock()
	targets := make([]*ClientInfo, 0, len(clientsByID))
	for id, c := range clientsByID {
		if id != senderID {
			targets = append(targets, c)
		}
	}
	clientsMu.RUnlock()

	for _, c := range targets {
		target := c // capture
		if delay > 0 {
			time.AfterFunc(delay, func() {
				conn.WriteToUDP(data, target.addr)
			})
		} else {
			conn.WriteToUDP(data, target.addr)
		}
	}
}

// send sends a message to a specific address, with optional delay.
func send(conn *net.UDPConn, msg Message, addr *net.UDPAddr, delay time.Duration) {
	data, err := encode(msg)
	if err != nil {
		log.Printf("[edge] encode error: %v", err)
		return
	}
	if delay > 0 {
		time.AfterFunc(delay, func() {
			conn.WriteToUDP(data, addr)
		})
	} else {
		conn.WriteToUDP(data, addr)
	}
}

// ─── Main server (also acts as edge node) ─────────────────────────────────────
// Usage: ./edge <name> <delay_ms>
// The server listens on 0.0.0.0:8000 by default.
// Pass --port <n> as optional 3rd arg to override.

func main() {
	if len(os.Args) < 3 {
		log.Fatal("Usage: ./edge <name> <delay_ms> [port]")
	}

	name := os.Args[1]
	delayInt, err := strconv.Atoi(os.Args[2])
	if err != nil {
		log.Fatalf("invalid delay: %v", err)
	}
	delay := time.Duration(delayInt) * time.Millisecond

	port := 8000
	if len(os.Args) >= 4 {
		port, err = strconv.Atoi(os.Args[3])
		if err != nil {
			log.Fatalf("invalid port: %v", err)
		}
	}

	addr, err := net.ResolveUDPAddr("udp4", fmt.Sprintf("0.0.0.0:%d", port))
	if err != nil {
		log.Fatal(err)
	}

	conn, err := net.ListenUDP("udp4", addr)
	if err != nil {
		log.Fatal(err)
	}
	defer conn.Close()

	fmt.Printf("[%s] UDP edge node listening on %s (delay=%dms)\n", name, conn.LocalAddr(), delayInt)

	buf := make([]byte, 65535)
	for {
		n, remoteAddr, err := conn.ReadFromUDP(buf)
		if err != nil {
			log.Printf("[%s] read error: %v", name, err)
			continue
		}

		data := make([]byte, n)
		copy(data, buf[:n])

		go handleMessage(conn, remoteAddr, data, delay)
	}
}

func handleMessage(conn *net.UDPConn, addr *net.UDPAddr, data []byte, delay time.Duration) {
	msg, err := decode(data)
	if err != nil {
		log.Printf("[edge] decode error from %s: %v", addr, err)
		return
	}

	switch msg.Type {

	// ── PING → reply PONG immediately (no delay, so ping measurement is accurate) ──
	case MsgPing:
		pong := Message{
			Type:        MsgPong,
			ClientID:    msg.ClientID,
			Seq:         msg.Seq,
			TimestampMs: nowMs(),
			Payload:     map[string]any{},
		}
		send(conn, pong, addr, 0)

	// ── DISCOVER → return edge list (just ourselves for now) ──
	case MsgDiscover:
		// For a single-node setup we return our own address as the only edge.
		// In a multi-node setup you would maintain a list of known peer edges.
		localAddr := conn.LocalAddr().(*net.UDPAddr)
		edgeList := Message{
			Type:        MsgEdgeList,
			ClientID:    msg.ClientID,
			Seq:         msg.Seq,
			TimestampMs: nowMs(),
			Payload: map[string]any{
				"edges": []map[string]any{
					{"host": "127.0.0.1", "port": localAddr.Port},
				},
				"ttl_ms": 10000,
			},
		}
		send(conn, edgeList, addr, 0)

	// ── REGISTER → store client mapping ──
	case MsgRegister:
		registerClient(msg.ClientID, addr)

	// ── PREDICTION → broadcast to all other clients (with delay), forward to host ──
	case MsgPrediction:
		// Make sure this client is registered (re-register if needed)
		clientsMu.RLock()
		_, known := clientsByID[msg.ClientID]
		clientsMu.RUnlock()
		if !known {
			registerClient(msg.ClientID, addr)
		}

		// Broadcast raw bytes to all peers with simulated delay.
		broadcast(conn, msg.ClientID, data, delay)

	default:
		log.Printf("[edge] unknown message type %q from %s", msg.Type, addr)
	}
}