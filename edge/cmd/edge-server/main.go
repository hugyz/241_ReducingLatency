package main

import (
	"fmt"
	"log"
	"net"
	"os"
	"sync"

	"edge/common"
)

// edgeSession represents one local client connected through this edge.
//
// Current behavior:
// - stores the client UDP address
// - stores a dedicated UDP connection to the main server
// - remembers client_id and origin info for debugging
//
// Still needed later:
// - may need explicit registration state
// - may need local client region if edge starts validating more fields
type edgeSession struct {
	clientAddr *net.UDPAddr
	hostConn   *net.UDPConn
	clientID   string
	originNode string
}

type EdgeServer struct {
	nodeName         string
	upstreamAddr     *net.UDPAddr
	upstreamAddrStr  string
	upstreamNodeName string
	edgeConn         *net.UDPConn
	displayIP        string
	delayMatrix      common.DelayMatrix
	upstreamDelay    time.Duration
	sessions         sync.Map
}

func main() {
	server := mustNewEdgeServer()
	defer server.edgeConn.Close()

	fmt.Printf("--- %s (Edge) ---\n", server.nodeName)
	fmt.Printf("Detected LAN IP: %s\n", server.displayIP)
	fmt.Printf("Listening on: %s\n", server.edgeConn.LocalAddr().String())
	fmt.Printf("Target: %s\n", server.upstreamAddrStr)
	fmt.Printf("Configured upstream delay: %v\n\n", server.upstreamDelay)

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
	upstreamDelay := common.DelayFor(delayMatrix, nodeName, upstreamNodeName)

	displayIP := common.PickBindIP(upstreamAddrStr)

	upstreamAddr, err := net.ResolveUDPAddr("udp4", upstreamAddrStr)
	if err != nil {
		log.Fatal(err)
	}

	laddr, err := net.ResolveUDPAddr("udp4", displayIP+":"+listenPort)
	if err != nil {
		log.Fatal(err)
	}

	edgeConn, err := net.ListenUDP("udp4", laddr)
	if err != nil {
		log.Fatal(err)
	}

	return &EdgeServer{
		nodeName:         nodeName,
		upstreamAddr:     upstreamAddr,
		upstreamAddrStr:  upstreamAddrStr,
		upstreamNodeName: upstreamNodeName,
		edgeConn:         edgeConn,
		displayIP:        displayIP,
		delayMatrix:      delayMatrix,
		upstreamDelay:    upstreamDelay,
	}
}

func (s *EdgeServer) Run() {
	buf := make([]byte, 4096)

	for {
		n, clientAddr, err := s.edgeConn.ReadFromUDP(buf)
		if err != nil {
			continue
		}

		data := append([]byte(nil), buf[:n]...)
		msg, _ := common.DecodeMessage(data)

		fmt.Printf("[RECV][EDGE %s] %d bytes from %s\n", s.nodeName, n, clientAddr)

		switch {
		case msg != nil && msg.Type == common.MsgPing:
			s.handlePing(msg, clientAddr)

		default:
			s.handleClientMessage(data, msg, clientAddr)
		}
	}
}

func (s *EdgeServer) handlePing(msg *common.Message, clientAddr *net.UDPAddr) {
	// Current behavior:
	// - replies to ping directly from the edge
	// - simulates reply delay using origin -> edge
	//
	// Still needed later:
	// - include region in ping payload from clients if not already present
	// - keep behavior aligned with main server ping handling

	pong := &common.Message{
		Type:        common.MsgPong,
		ClientID:    msg.ClientID,
		Seq:         msg.Seq,
		TimestampMs: msg.TimestampMs,
		Payload: map[string]interface{}{
			"edge":   s.nodeName,
			"origin": s.nodeName,
		},
	}

	resp, err := common.EncodeMessage(pong)
	if err != nil {
		fmt.Printf("[edge] failed to encode pong: %v\n", err)
		return
	}

	originNode := common.OriginFromMessage(msg, s.nodeName)
	replyDelay := common.DelayFor(s.delayMatrix, originNode, s.nodeName)

	common.ScheduleSend(s.edgeConn, resp, clientAddr, replyDelay)
}

func (s *EdgeServer) handleClientMessage(data []byte, msg *common.Message, clientAddr *net.UDPAddr) {
	// Current behavior:
	// - creates or reuses a session for this client
	// - broadcasts locally to other clients attached to this edge
	// - forwards the message upstream to main with configured edge -> main delay
	//
	// Still needed later:
	// - explicit REGISTER forwarding fields:
	//     registered_edge
	// - prediction forwarding rules to avoid loops when receiving from main
	// - separate handling for messages coming from main vs local client
	// - edge -> local-client delayed forwarding for downstream messages
    // - add client -> edge delay

	session := s.getOrCreateSession(clientAddr)
	if session == nil {
		return
	}

	if msg != nil {
		session.originNode = common.OriginFromMessage(msg, s.nodeName)
		session.clientID = msg.ClientID
	}

	// send the packet to other clients on this same edge
	s.broadcastLocal(clientAddr.String(), data)

	// Current upstream forwarding:
	// sends every non-ping message to main using the configured upstream delay.
	//
	// Later this may need:
	// - not forwarding messages that originated from main
	common.ScheduleWrite(session.hostConn, data, s.upstreamDelay)
}

func (s *EdgeServer) getOrCreateSession(clientAddr *net.UDPAddr) *edgeSession {
	key := clientAddr.String()

	if val, ok := s.sessions.Load(key); ok {
		return val.(*edgeSession)
	}

	hostConn, err := net.DialUDP("udp4", nil, s.upstreamAddr)
	if err != nil {
		fmt.Printf("[ERR] failed to dial upstream %s: %v\n", s.upstreamAddr, err)
		return nil
	}

	session := &edgeSession{
		clientAddr: clientAddr,
		hostConn:   hostConn,
	}

	s.sessions.Store(key, session)
	fmt.Printf("[NEW SESSION] %s\n", key)

	go s.runUpstreamReader(key, session)

	return session
}

func (s *EdgeServer) runUpstreamReader(sessionKey string, session *edgeSession) {
	// Current behavior:
	// - reads packets coming back from main on the per-session upstream socket
	// - relays them back to the local client using upstreamDelay
	//
	// Still needed later:
	// - this probably should use main -> edge and edge -> client logic separately
	// - currently it uses one delay value for the return path
	// - may need to fan out to multiple local clients if main broadcasts once to edge
	defer session.hostConn.Close()

	buf := make([]byte, 4096)
	for {
		n, _, err := session.hostConn.ReadFromUDP(buf)
		if err != nil {
			s.sessions.Delete(sessionKey)
			return
		}

		respData := append([]byte(nil), buf[:n]...)

		// Current behavior:
		// sends back only to the client that owns this session.
		//
		// Later, for true edge relay behavior, packets from main may need to be
		// distributed to all relevant local clients instead of only one session owner.
		common.ScheduleSend(s.edgeConn, respData, session.clientAddr, s.upstreamDelay)
	}
}

func (s *EdgeServer) broadcastLocal(senderKey string, data []byte) {
	// Current behavior:
	// - forwards incoming client packets to every other local client on this edge
	//
	// Still needed later:
	// - should only do this for prediction messages
    // - should add edge -> client delay
	s.sessions.Range(func(key, value interface{}) bool {
		if key.(string) != senderKey {
			_, _ = s.edgeConn.WriteToUDP(data, value.(*edgeSession).clientAddr)
		}
		return true
	})
}