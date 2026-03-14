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
	NodeRegion string
	Addr       *net.UDPAddr
}

type MainServer struct {
	common.Server
	Edges map[string]*EdgeInfo
}

func main() {
	server := mustNewMainServer()
	defer server.Conn.Close()

	fmt.Printf("--- %s (Main Server) ---\n", server.NodeRegion)
	fmt.Printf("Listening on: %s\n\n", server.Conn.LocalAddr().String())

	server.Run()
}

func mustNewMainServer() *MainServer {
	if len(os.Args) < 3 || len(os.Args) > 4 {
		log.Fatal("Usage: <node_region> <listen_addr> [delay_config.json]")
	}

	nodeRegion := os.Args[1]
	listenAddrStr := os.Args[2]

	var delayConfigPath string
	if len(os.Args) == 4 {
		delayConfigPath = os.Args[3]
	}

	laddr, err := net.ResolveUDPAddr("udp4", listenAddrStr)
	if err != nil {
		log.Fatal(err)
	}

	conn, err := net.ListenUDP("udp4", laddr)
	if err != nil {
		log.Fatal(err)
	}

	var delayMatrix common.DelayMatrix
	if delayConfigPath != "" {
		delayMatrix = common.MustLoadDelayMatrix(delayConfigPath)
	}

	return &MainServer{
		Server: common.NewServer(nodeRegion, conn, laddr, delayMatrix),
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
		msg, err := common.DecodeMessage(data)
		if err != nil || msg == nil {
			continue
		}

		switch msg.Type {
		case common.MsgPing:
			common.HandlePing(s.Conn, s.NodeRegion, s.DelayMatrix, msg, addr)

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
			"region": edge.NodeRegion,
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

	registeredRegion := s.NodeRegion
	if v, ok := common.GetString(msg.Payload, "registered_region"); ok && v != "" {
		registeredRegion = v
	}

	s.Clients[msg.ClientID] = &common.RegisteredClient{
		ClientID:         msg.ClientID,
		Region:           region,
		RegisteredRegion: registeredRegion,
		Addr:             addr, // either client addr (registered to main) or edge addr
	}

	if registeredRegion != s.NodeRegion {
		s.Edges[registeredRegion] = &EdgeInfo{
			NodeRegion: registeredRegion,
			Addr:       addr,
		}
	}

	fmt.Printf("[main] REGISTER client=%s region=%s registered_region=%s from=%s\n",
		msg.ClientID, region, registeredRegion, addr.String())
}

func (s *MainServer) handlePrediction(msg *common.Message, raw []byte, addr *net.UDPAddr) {
	sender, ok := s.Clients[msg.ClientID]
	if !ok {
		fmt.Printf("[main] ignoring PREDICTION from unregistered client=%s\n", msg.ClientID)
		return
	}

	// simulate client -> main delay
	var inboundDelay time.Duration

	if sender.RegisteredRegion == s.NodeRegion {
		inboundDelay = common.DelayDuration(s.DelayMatrix, sender.Region, s.NodeRegion)
	} else {
		inboundDelay = common.DelayDuration(s.DelayMatrix, sender.RegisteredRegion, s.NodeRegion)
	}
	fmt.Printf("[main] PREDICTION client=%s region=%s registered_region=%s from=%s inbound_delay=%v\n",
		msg.ClientID, sender.Region, sender.RegisteredRegion, addr.String(), inboundDelay)

	go func(senderClientID string, data []byte, delay time.Duration) {
		if delay > 0 {
			time.Sleep(delay)
		}
		s.broadcastPrediction(data, senderClientID)
	}(msg.ClientID, append([]byte(nil), raw...), inboundDelay)
}

// right now this forwards predictions to all other EDGE NODES as well as the
// main server's registered clients, but can change to all other CLIENTS if makes more sense
func (s *MainServer) broadcastPrediction(data []byte, senderClientID string) {
	sender, ok := s.Clients[senderClientID]
	if !ok {
		return
	}

	originRegion := sender.RegisteredRegion
	sentEdges := map[string]bool{}

	// Send directly to clients attached to main
	s.BroadcastLocal(data, senderClientID)

	// Send once to each other edge, but not back to the sender's edge
	for clientID, client := range s.Clients {
		if clientID == senderClientID {
			continue
		}
		if client.RegisteredRegion == s.NodeRegion {
			continue
		}
		if client.RegisteredRegion == originRegion {
			continue
		}
		if sentEdges[client.RegisteredRegion] {
			continue
		}

		edge, ok := s.Edges[client.RegisteredRegion]
		if !ok || edge.Addr == nil {
			continue
		}

		delay := common.DelayDuration(s.DelayMatrix, s.NodeRegion, client.RegisteredRegion)

		fmt.Printf(
			"[main] BROADCAST source=%s(%s,%s) dest_edge=%s delay=%v to=%s\n",
			sender.ClientID,
			sender.Region,
			originRegion,
			client.RegisteredRegion,
			delay,
			edge.Addr.String(),
		)

		s.SendAfter(data, edge.Addr, delay)
		sentEdges[client.RegisteredRegion] = true
	}
}
