package common

func GetString(m map[string]interface{}, key string) (string, bool) {
	if m == nil {
		return "", false
	}

	v, ok := m[key]
	if !ok {
		return "", false
	}

	s, ok := v.(string)
	return s, ok
}

func GetInt(m map[string]interface{}, key string) (int, bool) {
	if m == nil {
		return 0, false
	}

	v, ok := m[key]
	if !ok {
		return 0, false
	}

	switch n := v.(type) {
	case float64:
		return int(n), true
	case int:
		return n, true
	default:
		return 0, false
	}
}