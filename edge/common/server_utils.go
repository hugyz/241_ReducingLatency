package common

import (
	"fmt"
	"net"
	"time"
)

func HandlePing(
	conn *net.UDPConn,
	nodeName string,
	delayMatrix DelayMatrix,
	msg *Message,
	addr *net.UDPAddr,
) {

	clientRegion, _ := GetString(msg.Payload, "region")

	pong := &Message{
		Type:        MsgPong,
		ClientID:    msg.ClientID,
		Seq:         msg.Seq,
		TimestampMs: msg.TimestampMs,
		Payload: map[string]interface{}{
			"edge":   nodeName,
			"origin": nodeName,
		},
	}

	resp, err := EncodeMessage(pong)
	if err != nil {
		fmt.Printf("[server] failed to encode pong: %v\n", err)
		return
	}

	delay := DelayDuration(delayMatrix, clientRegion, nodeName)

	fmt.Printf(
		"[server] PONG client=%s client_region=%s server=%s delay=%v to=%s\n",
		msg.ClientID,
		clientRegion,
		nodeName,
		delay,
		addr.String(),
	)

	ScheduleSend(conn, resp, addr, delay)
}

// returns the delay between two regions as a time.Duration.
func DelayDuration(matrix DelayMatrix, from, to string) time.Duration {
	if matrix == nil {
		return 0
	}

	delay := DelayFor(matrix, from, to)
	if delay < 0 {
		return 0
	}

	return delay
}