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
	upstreamAddr    *net.UDPAddr
	upstreamAddrStr string
	upstreamRegion  string
	serverConns     map[string]*net.UDPConn
}

func main() {
	server := mustNewEdgeServer()
	defer server.Conn.Close()

	fmt.Printf("--- %s (Edge) ---\n", server.NodeRegion)
	fmt.Printf("Listening on: %s\n", server.Conn.LocalAddr().String())
	fmt.Printf("Target: %s\n", server.upstreamAddrStr)
	fmt.Printf("\n")

	server.Run()
}

func mustNewEdgeServer() *EdgeServer {
	if len(os.Args) != 5 {
		log.Fatal("Usage: <node_region> <upstream_addr> <delay_config.json> <upstream_region>")
	}

	nodeRegion := os.Args[1]
	upstreamAddrStr := os.Args[2]
	delayConfigPath := os.Args[3]
	upstreamRegion := os.Args[4]

	delayMatrix := common.MustLoadDelayMatrix(delayConfigPath)

	displayIP := common.PickBindIP(upstreamAddrStr)

	upstreamAddr, err := net.ResolveUDPAddr("udp4", upstreamAddrStr)
	if err != nil {
		log.Fatal(err)
	}

	laddr, err := net.ResolveUDPAddr("udp4", displayIP+":0")
	if err != nil {
		log.Fatal(err)
	}

	conn, err := net.ListenUDP("udp4", laddr)
	if err != nil {
		log.Fatal(err)
	}

	return &EdgeServer{
		Server:          common.NewServer(nodeRegion, conn, conn.LocalAddr().(*net.UDPAddr), delayMatrix),
		upstreamAddr:    upstreamAddr,
		upstreamAddrStr: upstreamAddrStr,
		upstreamRegion:  upstreamRegion,
		serverConns:     make(map[string]*net.UDPConn),
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

		fmt.Printf("[RECV][EDGE %s] %d bytes from %s\n", s.NodeRegion, n, addr)

		switch {
		case msg != nil && msg.Type == common.MsgPing:
			s.handlePing(msg, addr)

		case msg != nil && msg.Type == common.MsgRegister:
			s.handleRegister(msg, addr)

		default:
			s.handleClientMessage(data, msg, addr)
		}
	}
}

func (s *EdgeServer) handleServerMessage(data []byte) {
	// Relay packet coming back from main to all local clients.
	// The edge handles the Edge -> Client delay.
	s.BroadcastLocal(data, "")
}

func (s *EdgeServer) handlePing(msg *common.Message, clientAddr *net.UDPAddr) {
	pong := &common.Message{
		Type:        common.MsgPong,
		ClientID:    msg.ClientID,
		Seq:         msg.Seq,
		TimestampMs: msg.TimestampMs,
		Payload: map[string]interface{}{
			"edge":   s.NodeRegion,
			"origin": s.NodeRegion,
		},
	}

	resp, err := common.EncodeMessage(pong)
	if err != nil {
		fmt.Printf("[edge] failed to encode pong: %v\n", err)
		return
	}

	originRegion := common.OriginFromMessage(msg, s.NodeRegion)
	replyDelay := common.DelayMS(s.DelayMatrix, originRegion, s.NodeRegion)

	s.SendAfter(resp, clientAddr, replyDelay)
}

func (s *EdgeServer) handleRegister(msg *common.Message, clientAddr *net.UDPAddr) {
	region, _ := common.GetString(msg.Payload, "region")
	client := &common.RegisteredClient{
		ClientID:         msg.ClientID,
		Region:           region,
		RegisteredRegion: s.NodeRegion,
		Addr:             clientAddr,
	}

	serverConn, err := net.DialUDP("udp4", nil, s.upstreamAddr)
	if err != nil {
		fmt.Printf("[edge] failed to bind new port for client %s: %v\n", msg.ClientID, err)
		return
	}
	s.serverConns[msg.ClientID] = serverConn

	s.Clients[msg.ClientID] = client
	fmt.Printf("[NEW CLIENT] %s registered, bound upstream port %v\n", msg.ClientID, serverConn.LocalAddr())

	// Swap the region with the Edge's own region
	if msg.Payload == nil {
		msg.Payload = make(map[string]interface{})
	}
	msg.Payload["region"] = s.NodeRegion

	forwardData, err := common.EncodeMessage(msg)
	if err != nil {
		fmt.Printf("[edge] failed to encode register: %v\n", err)
		return
	}

	inboundDelay := s.DelayFromClient(client)
	time.AfterFunc(inboundDelay, func() {
		_, _ = serverConn.Write(forwardData)
	})

	go s.runUpstreamReader(serverConn)
}

func (s *EdgeServer) handleClientMessage(data []byte, msg *common.Message, clientAddr *net.UDPAddr) {
	if msg == nil {
		return
	}

	client, ok := s.Clients[msg.ClientID]
	if !ok {
		region, _ := common.GetString(msg.Payload, "region")
		client = &common.RegisteredClient{
			ClientID:         msg.ClientID,
			Region:           region,
			RegisteredRegion: s.NodeRegion,
			Addr:             clientAddr,
		}
		s.Clients[msg.ClientID] = client
		fmt.Printf("[NEW CLIENT] %s\n", msg.ClientID)
	} else {
		client.Addr = clientAddr
	}

	inboundDelay := s.DelayFromClient(client)

	time.AfterFunc(inboundDelay, func() {
		// Forward to main server using the dedicated connection if available
		if conn, ok := s.serverConns[msg.ClientID]; ok {
			_, _ = conn.Write(data)
		} else {
			_, _ = s.Conn.WriteToUDP(data, s.upstreamAddr)
		}

		// Forward incoming client packets to every other local client on this edge
		s.BroadcastLocal(data, msg.ClientID)
	})
}

func (s *EdgeServer) runUpstreamReader(conn *net.UDPConn) {
	buf := make([]byte, 4096)
	for {
		n, err := conn.Read(buf)
		if err != nil {
			break
		}
		data := append([]byte(nil), buf[:n]...)
		s.handleServerMessage(data)
	}
}
