package main

import (
	"fmt"
	"log"
	"net"
	"os"
	"strconv"
	"sync"
	"time"
)

// Client represents a paired connection between a remote device and the target host.
type Client struct {
	ce   *net.TCPConn // client <-> edge
	eh   *net.TCPConn // edge <-> host
	addr string
}

// Global map to track active clients for broadcasting.
var clients sync.Map

// GetExtarnalIPv4 finds non-loopback IPv4 addresses on the local machine.
func GetExtarnalIPv4() []string {
	var ips []string
	addrs, _ := net.InterfaceAddrs()
	for _, address := range addrs {
		if ipnet, ok := address.(*net.IPNet); ok && ipnet.IP.To4() != nil && !ipnet.IP.IsLoopback() {
			ips = append(ips, ipnet.IP.String())
		}
	}
	return ips
}

// GetTCPListener attempts to bind a TCP listener to an external IP on an ephemeral port.
func GetTCPListener() (*net.TCPListener, error) {
	for _, ip := range GetExtarnalIPv4() {
		if addr, err := net.ResolveTCPAddr("tcp4", ip+":0"); err == nil {
			if listener, err := net.ListenTCP("tcp4", addr); err == nil {
				return listener, nil
			}
		}
	}
	return nil, fmt.Errorf("no external IP found")
}

// handleClient manages the bidirectional data flow and broadcast logic for a single client.
func handleClient(client *Client, delay time.Duration) {
	defer client.ce.Close()
	defer client.eh.Close()
	defer clients.Delete(client.addr)

	// Channel to signal if either side of the proxy closes.
	done := make(chan bool, 2)

	// 1. Client -> Edge -> (Broadcast to Peers + Delayed Host)
	go func() {
		buf := make([]byte, 4096) // Fixed syntax: []byte instead of byte[]
		for {
			n, err := client.ce.Read(buf)
			if err != nil {
				done <- true
				return
			}

			// Create a copy of the data because buf will be reused in the next iteration.
			data := make([]byte, n)
			copy(data, buf[:n])

			// Broadcast to other clients immediately.
			broadcast(client.addr, data)

			// Send to Host after M ms delay.
			time.AfterFunc(delay, func() {
				client.eh.Write(data)
			})
		}
	}()

	// 2. Host -> Edge -> Delayed Client
	go func() {
		buf := make([]byte, 4096) // Fixed syntax: []byte instead of byte[]
		for {
			n, err := client.eh.Read(buf)
			if err != nil {
				done <- true
				return
			}

			data := make([]byte, n)
			copy(data, buf[:n])

			// Send back to this specific client after M ms delay.
			time.AfterFunc(delay, func() {
				client.ce.Write(data)
			})
		}
	}()

	<-done
	fmt.Printf("Connection closed for %s\n", client.addr)
}

// broadcast sends the provided data to every client except the sender.
func broadcast(senderAddr string, data []byte) {
	clients.Range(func(key, value interface{}) bool {
		targetAddr := key.(string)
		client := value.(*Client)

		if targetAddr != senderAddr {
			// We write directly here; if the client's buffer is full,
			// this could block. In a production environment, you might
			// use a per-client egress channel.
			client.ce.Write(data)
		}
		return true
	})
}

func main() {
	if len(os.Args) != 4 {
		log.Fatal("Usage: <name> <host_addr> <delay_ms>")
	}

	name := os.Args[1]
	hostAddrStr := os.Args[2]

	// Parse M (delay in milliseconds) from command line.
	delayInt, err := strconv.Atoi(os.Args[3])
	if err != nil {
		log.Fatalf("Invalid delay value: %v", err)
	}
	delay := time.Duration(delayInt) * time.Millisecond

	listener, err := GetTCPListener()
	if err != nil {
		log.Panic(err)
	}
	fmt.Printf("%s listening on %s\n", name, listener.Addr())

	hostAddr, err := net.ResolveTCPAddr("tcp4", hostAddrStr)
	if err != nil {
		log.Panic(err)
	}

	for {
		// Accept incoming client connection.
		ce, err := listener.AcceptTCP()
		if err != nil {
			fmt.Printf("Accept error: %v\n", err)
			continue
		}

		fmt.Printf("Got connection from %s\n", ce.RemoteAddr())

		// Establish a unique connection to the host for this specific client.
		eh, err := net.DialTCP("tcp4", nil, hostAddr)
		if err != nil {
			fmt.Printf("Could not connect to host for client %s: %v\n", ce.RemoteAddr(), err)
			ce.Close()
			continue
		}

		client := &Client{
			ce:   ce,
			eh:   eh,
			addr: ce.RemoteAddr().String(),
		}

		// Store client in the map and start processing.
		clients.Store(client.addr, client)
		go handleClient(client, delay)
	}
}
