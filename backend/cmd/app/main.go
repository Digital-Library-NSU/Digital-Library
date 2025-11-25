package main

import (
	"log"

	"digital_library/internal/infrastructure/server"
)

func main() {
	if err := server.Run("localhost:8080"); err != nil {
		log.Fatal(err)
	}
}
