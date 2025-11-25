package server

import (
	"github.com/gin-gonic/gin"

	"digital_library/internal/infrastructure/handlers"
)

func Run(addr string) error {
	router := gin.Default()
	router.POST("/api/books/upload", handlers.UploadBook)
	// router.POST("/api/books/upload", handlers.UploadBook)
	// router.POST("/api/books/upload", handlers.UploadBook)
	// router.POST("/api/books/upload", handlers.UploadBook)
	return router.Run(addr)
}
