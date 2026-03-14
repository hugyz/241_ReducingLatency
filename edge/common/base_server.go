package common

import (
	"fmt"
	"net"
	"time"
)

type RegisteredClient struct {
	ClientID string
	Region   string
	Addr     *net.UDPAddr // the client's address if registered to main, or edge address
}

type Server struct {
	NodeRegion  string
	Conn        *net.UDPConn
	ListenAddr  *net.UDPAddr
	DelayMatrix DelayMatrix
	Clients     map[string]*RegisteredClient
}

func NewServer(nodeRegion string, conn *net.UDPConn, listenAddr *net.UDPAddr, delayMatrix DelayMatrix) Server {
	return Server{
		NodeRegion:  nodeRegion,
		Conn:        conn,
		ListenAddr:  listenAddr,
		DelayMatrix: delayMatrix,
		Clients:     make(map[string]*RegisteredClient),
	}
}

func (s *Server) SendAfter(data []byte, addr *net.UDPAddr, delay time.Duration) {
	if delay > 0 {
		time.AfterFunc(delay, func() {
			_, _ = s.Conn.WriteToUDP(data, addr)
		})
	} else {
		_, _ = s.Conn.WriteToUDP(data, addr)
	}
}

func (s *Server) HandlePing(msg *Message, addr *net.UDPAddr) {
	clientRegion, _ := GetString(msg.Payload, "region")
	if clientRegion == "" {
		clientRegion = s.NodeRegion
	}

	pong := &Message{
		Type:        MsgPong,
		ClientID:    msg.ClientID,
		Seq:         msg.Seq,
		TimestampMs: msg.TimestampMs,
		Payload: map[string]interface{}{
			"edge":   s.NodeRegion,
			"origin": s.NodeRegion,
		},
	}

	resp, err := EncodeMessage(pong)
	if err != nil {
		fmt.Printf("[server] failed to encode pong: %v\n", err)
		return
	}

	outboundDelay := DelayDuration(s.DelayMatrix, s.NodeRegion, clientRegion)

	// The inbound delay was already simulated by waiting before executing this handler,
	// so we only need to add the outbound delay for the return trip!
	s.SendAfter(resp, addr, outboundDelay)
}

// InboundDelayFromMessage returns the delay from the message sender to this server.
func (s *Server) InboundDelayFromMessage(msg *Message) time.Duration {
	if msg == nil {
		return 0
	}
	clientRegion := ""
	if client, ok := s.Clients[msg.ClientID]; ok {
		clientRegion = client.Region
	}
	if clientRegion == "" {
		clientRegion, _ = GetString(msg.Payload, "region")
	}
	if clientRegion == "" {
		fmt.Printf("Client %s does not have a region\n", msg.ClientID)
		clientRegion = s.NodeRegion
	}
	return DelayDuration(s.DelayMatrix, clientRegion, s.NodeRegion)
}

// DelayDuration returns the delay between two regions as a time.Duration.
func DelayDuration(matrix DelayMatrix, from, to string) time.Duration {
	if matrix == nil {
		return 0
	}

	delay := DelayMS(matrix, from, to)
	if delay < 0 {
		return 0
	}

	return delay
}

func (s *Server) DelayToClient(client *RegisteredClient) time.Duration {
	return DelayDuration(s.DelayMatrix, s.NodeRegion, client.Region)
}

func (s *Server) DelayFromClient(client *RegisteredClient) time.Duration {
	return DelayDuration(s.DelayMatrix, client.Region, s.NodeRegion)
}

func (s *Server) DelayToClientMs(client *RegisteredClient) int64 {
	return s.DelayToClient(client).Milliseconds()
}

func (s *Server) DelayFromClientMs(client *RegisteredClient) int64 {
	return s.DelayFromClient(client).Milliseconds()
}

func (s *Server) BroadcastLocal(data []byte, excludeClientID string) {
	for clientID, client := range s.Clients {
		if clientID == excludeClientID {
			continue
		}
		if client.Addr == nil {
			continue
		}
		delay := s.DelayToClient(client)
		s.SendAfter(data, client.Addr, delay)
	}
}
