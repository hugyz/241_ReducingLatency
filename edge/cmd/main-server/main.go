package main

import (
	"fmt"
	"log"
	"net"
	"os"
	"time"

	"edge/common"
)

type EdgeInfo struct {
	Region string
	Addr   *net.UDPAddr
}

type MainServer struct {
	common.Server
	Edges map[string]*EdgeInfo
}

func main() {
	server := mustNewMainServer()
	defer server.Conn.Close()

	fmt.Printf("--- %s (Main Server) ---\n", server.NodeRegion)
	fmt.Printf("Listening on: %s\n\n", server.ListenAddr.String())

	server.Run()
}

func mustNewMainServer() *MainServer {
	if len(os.Args) != 3 {
		log.Fatal("Usage: <node_region> <delay_config.json>")
	}

	region := os.Args[1]
	delayMatrix := common.MustLoadDelayMatrix(os.Args[2])

	if _, ok := delayMatrix[region]; !ok {
		log.Panicf("FATAL: Main server region %q not found in delay config", region)
	}

	laddr, err := net.ResolveUDPAddr("udp4", "0.0.0.0:0")
	if err != nil {
		log.Fatal(err)
	}

	conn, err := net.ListenUDP("udp4", laddr)
	if err != nil {
		log.Fatal(err)
	}

	// Combine the detected LAN IP with the OS-assigned port for discovery
	localIP := common.GetLocalIP()
	actualPort := conn.LocalAddr().(*net.UDPAddr).Port
	displayAddr, err := net.ResolveUDPAddr("udp4", fmt.Sprintf("%s:%d", localIP, actualPort))
	if err != nil {
		log.Fatal(err)
	}

	return &MainServer{
		Server: common.NewServer(region, conn, displayAddr, delayMatrix),
		Edges:  make(map[string]*EdgeInfo),
	}
}

func (s *MainServer) Run() {
	buf := make([]byte, 4096)

	for {
		n, addr, err := s.Conn.ReadFromUDP(buf)
		if err != nil {
			continue
		}

		data := append([]byte(nil), buf[:n]...)

		fmt.Printf("[main] Received %d bytes from %s\n", n, addr.String())

		msg, err := common.DecodeMessage(data)
		if err != nil || msg == nil {
			fmt.Printf("[main] Failed to decode message: %v\nRaw data: %s\n", err, string(data))
			continue
		}

		switch msg.Type {
		case common.MsgPing:
			s.HandlePing(msg, addr)

		case common.MsgDiscover:
			s.handleDiscover(msg, addr)

		case common.MsgRegister:
			s.handleRegister(msg, addr)

		case common.MsgPrediction:
			s.handlePrediction(msg, data, addr)

		default:
			fmt.Printf("[main] ignoring unsupported msg type=%s from=%s\n", msg.Type, addr.String())
		}
	}
}

func (s *MainServer) handleDiscover(msg *common.Message, addr *net.UDPAddr) {
	servers := []map[string]interface{}{
		{
			"host":   s.ListenAddr.IP.String(),
			"port":   s.ListenAddr.Port,
			"region": s.NodeRegion,
			"kind":   "main",
		},
	}

	for _, edge := range s.Edges {
		servers = append(servers, map[string]interface{}{
			"host":   edge.Addr.IP.String(),
			"port":   edge.Addr.Port,
			"region": edge.Region,
			"kind":   "edge",
		})
	}

	respMsg := &common.Message{
		Type:        common.MsgEdgeList,
		ClientID:    msg.ClientID,
		Seq:         msg.Seq,
		TimestampMs: time.Now().UnixMilli(),
		Payload: map[string]interface{}{
			"edges":  servers,
			"ttl_ms": 10000,
		},
	}

	resp, err := common.EncodeMessage(respMsg)
	if err != nil {
		fmt.Printf("[main] failed to encode edge list: %v\n", err)
		return
	}

	s.SendAfter(resp, addr, 0)
}

func (s *MainServer) handleRegister(msg *common.Message, addr *net.UDPAddr) {
	region, _ := common.GetString(msg.Payload, "region")

	if v, _ := common.GetString(msg.Payload, "registered_edge"); v == "self" {
		if region != "" && region != s.NodeRegion {
			s.Edges[region] = &EdgeInfo{
				Region: region,
				Addr:   addr,
			}
			fmt.Printf("[main] Registered edge server %s at %s\n", region, addr.String())
		}
		return
	}

	s.Clients[msg.ClientID] = &common.RegisteredClient{
		ClientID: msg.ClientID,
		Region:   region,
		Addr:     addr,
	}

	fmt.Printf("[main] REGISTER client=%s region=%s from=%s\n",
		msg.ClientID, region, addr.String())
}

func (s *MainServer) handlePrediction(msg *common.Message, raw []byte, addr *net.UDPAddr) {
	sender, ok := s.Clients[msg.ClientID]
	if !ok {
		fmt.Printf("[main] ignoring PREDICTION from unregistered client=%s\n", msg.ClientID)
		return
	}

	// simulate client -> main delay
	inboundDelay := s.DelayFromClient(sender)
	fmt.Printf("[main] PREDICTION client=%s region=%s from=%s inbound_delay=%v\n",
		msg.ClientID, sender.Region, addr.String(), inboundDelay)

	go func(senderClientID string, data []byte, delay time.Duration) {
		if delay > 0 {
			time.Sleep(delay)
		}
		s.BroadcastLocal(data, senderClientID)
	}(msg.ClientID, append([]byte(nil), raw...), inboundDelay)
}
