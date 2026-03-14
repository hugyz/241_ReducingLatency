package main

import (
	"fmt"
	"log"
	"net"
	"os"
	"time"

	"edge/common"
)

type EdgeServer struct {
	common.Server
	upstreamAddr     *net.UDPAddr
	upstreamAddrStr  string
	upstreamNodeName string
}

func main() {
	server := mustNewEdgeServer()
	defer server.Conn.Close()

	fmt.Printf("--- %s (Edge) ---\n", server.NodeName)
	fmt.Printf("Listening on: %s\n", server.Conn.LocalAddr().String())
	fmt.Printf("Target: %s\n", server.upstreamAddrStr)
	fmt.Printf("\n")

	server.Run()
}

func mustNewEdgeServer() *EdgeServer {
	if len(os.Args) != 6 {
		log.Fatal("Usage: <node_name> <upstream_addr> <listen_port> <delay_config.json> <upstream_node_name>")
	}

	nodeName := os.Args[1]
	upstreamAddrStr := os.Args[2]
	listenPort := os.Args[3]
	delayConfigPath := os.Args[4]
	upstreamNodeName := os.Args[5]

	delayMatrix := common.MustLoadDelayMatrix(delayConfigPath)

	displayIP := common.PickBindIP(upstreamAddrStr)

	upstreamAddr, err := net.ResolveUDPAddr("udp4", upstreamAddrStr)
	if err != nil {
		log.Fatal(err)
	}

	laddr, err := net.ResolveUDPAddr("udp4", displayIP+":"+listenPort)
	if err != nil {
		log.Fatal(err)
	}

	conn, err := net.ListenUDP("udp4", laddr)
	if err != nil {
		log.Fatal(err)
	}

	return &EdgeServer{
		Server:           common.NewServer(nodeName, conn, laddr, delayMatrix),
		upstreamAddr:     upstreamAddr,
		upstreamAddrStr:  upstreamAddrStr,
		upstreamNodeName: upstreamNodeName,
	}
}

func (s *EdgeServer) Run() {
	buf := make([]byte, 4096)

	for {
		n, addr, err := s.Conn.ReadFromUDP(buf)
		if err != nil {
			continue
		}

		data := append([]byte(nil), buf[:n]...)
		msg, _ := common.DecodeMessage(data)

		// Intercept packets from upstream server
		if addr.String() == s.upstreamAddr.String() {
			s.handleServerMessage(data)
			continue
		}

		fmt.Printf("[RECV][EDGE %s] %d bytes from %s\n", s.NodeName, n, addr)

		switch {
		case msg != nil && msg.Type == common.MsgPing:
			s.handlePing(msg, addr)

		default:
			s.handleClientMessage(data, msg, addr)
		}
	}
}

func (s *EdgeServer) handleServerMessage(data []byte) {
	// Relay packet coming back from main to all local clients.
	// The edge handles the Edge -> Client delay.
	for _, client := range s.Clients {
		outDelay := common.DelayDuration(s.DelayMatrix, s.NodeName, client.Region)
		s.SendAfter(data, client.Addr, outDelay)
	}
}

func (s *EdgeServer) handlePing(msg *common.Message, clientAddr *net.UDPAddr) {
	pong := &common.Message{
		Type:        common.MsgPong,
		ClientID:    msg.ClientID,
		Seq:         msg.Seq,
		TimestampMs: msg.TimestampMs,
		Payload: map[string]interface{}{
			"edge":   s.NodeName,
			"origin": s.NodeName,
		},
	}

	resp, err := common.EncodeMessage(pong)
	if err != nil {
		fmt.Printf("[edge] failed to encode pong: %v\n", err)
		return
	}

	originNode := common.OriginFromMessage(msg, s.NodeName)
	replyDelay := common.DelayMS(s.DelayMatrix, originNode, s.NodeName)

	s.SendAfter(resp, clientAddr, replyDelay)
}

func (s *EdgeServer) handleClientMessage(data []byte, msg *common.Message, clientAddr *net.UDPAddr) {
	if msg == nil {
		return
	}

	client, ok := s.Clients[msg.ClientID]
	if !ok {
		region, _ := common.GetString(msg.Payload, "region")
		client = &common.RegisteredClient{
			ClientID:     msg.ClientID,
			Region:       region,
			RegisteredTo: s.NodeName,
			Addr:         clientAddr,
		}
		s.Clients[msg.ClientID] = client
		fmt.Printf("[NEW CLIENT] %s\n", msg.ClientID)
	} else {
		client.Addr = clientAddr
	}

	inboundDelay := common.DelayDuration(s.DelayMatrix, client.Region, s.NodeName)

	time.AfterFunc(inboundDelay, func() {
		// Forward to main server immediately (server handles edge->main delay)
		_, _ = s.Conn.WriteToUDP(data, s.upstreamAddr)

		// Forward incoming client packets to every other local client on this edge
		for _, c := range s.Clients {
			if c.ClientID != msg.ClientID {
				outDelay := common.DelayDuration(s.DelayMatrix, s.NodeName, c.Region)
				s.SendAfter(data, c.Addr, outDelay)
			}
		}
	})
}
