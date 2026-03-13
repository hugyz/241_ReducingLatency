package common

import "encoding/json"
import "net"

const (
    MsgPing       = "PING"
    MsgPong       = "PONG"
    MsgDiscover   = "DISCOVER"
    MsgEdgeList   = "EDGE_LIST"
    MsgRegister   = "REGISTER"
    MsgPrediction = "PREDICTION"
    MsgState      = "STATE_UPDATE"
    MsgRollback   = "ROLLBACK"
)

type Message struct {
    Type        string                 `json:"type"`
    ClientID    string                 `json:"client_id,omitempty"`
    Seq         int                    `json:"seq,omitempty"`
    TimestampMs int64                  `json:"timestamp_ms,omitempty"`
    Payload     map[string]interface{} `json:"payload,omitempty"`
}

type ClientInfo struct {
	ClientID       string
	Region         string
	RegisteredServer string
	Addr           *net.UDPAddr
}

func DecodeMessage(data []byte) (*Message, error) {
    var msg Message
    if err := json.Unmarshal(data, &msg); err != nil {
        return nil, err
    }
    if msg.Payload == nil {
        msg.Payload = map[string]interface{}{}
    }
    return &msg, nil
}

func EncodeMessage(msg *Message) ([]byte, error) { return json.Marshal(msg) }
