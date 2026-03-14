package common

import (
	"encoding/json"
	"fmt"
	"os"
	"time"
)

type DelayMatrix map[string]map[string]int

func MustLoadDelayMatrix(path string) DelayMatrix {
	b, err := os.ReadFile(path)
	if err != nil {
		panic(fmt.Errorf("read delay config %s: %w", path, err))
	}
	var m DelayMatrix
	if err := json.Unmarshal(b, &m); err != nil {
		panic(fmt.Errorf("parse delay config %s: %w", path, err))
	}
	return m
}

func DelayMS(m DelayMatrix, from, to string) time.Duration {
	if row, ok := m[from]; ok {
		if ms, ok := row[to]; ok {
			return time.Duration(ms) * time.Millisecond
		}
	}
	return 0
}
