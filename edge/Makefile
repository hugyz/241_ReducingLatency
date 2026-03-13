MAIN=main-server
EDGE=edge-server

build:
	go build -o $(MAIN) ./cmd/main-server
	go build -o $(EDGE) ./cmd/edge-server

clean:
	rm -f $(MAIN) $(EDGE)