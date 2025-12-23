import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, EventEmitter, inject, Output } from '@angular/core';
import { BookDataService } from '../../../../core/services/book-data.service';

@Component({
    selector: 'app-upload-book-modal',
    imports: [CommonModule],
    templateUrl: './upload-book-modal.component.html',
    styleUrl: './upload-book-modal.component.scss',
})
export class UploadBookModalComponent {
    @Output() close = new EventEmitter<boolean>();

    private bookService = inject(BookDataService);

    selectedFile: File | null = null;
    isUploading = false;
    isSuccess = false;
    isDragOver = false;
    errorMessage = '';

    onFileSelected(event: any) {
        const file = event.target.files[0];
        if (file) {
            this.selectedFile = file;
            this.errorMessage = '';
        }
    }

    upload() {
        if (!this.selectedFile) return;

        this.isUploading = true;
        this.errorMessage = '';

        this.bookService.uploadBook(this.selectedFile).subscribe({
            next: () => {
                this.isUploading = false;
                this.isSuccess = true;
            },
            error: (err: HttpErrorResponse) => {
                this.isUploading = false;
                console.error('Upload error:', err);

                if (err.error && err.error.detail) {
                    this.errorMessage = err.error.detail;
                } else {
                    this.errorMessage =
                        'An unexpected error occurred. Please try again.';
                }
            },
        });
    }

    closeModal() {
        this.close.emit(this.isSuccess);
    }

    onDragOver(event: DragEvent) {
        event.preventDefault();
        event.stopPropagation();
        this.isDragOver = true;
    }

    onDragLeave(event: DragEvent) {
        event.preventDefault();
        event.stopPropagation();
        this.isDragOver = false;
    }

    onDrop(event: DragEvent) {
        event.preventDefault();
        event.stopPropagation();
        this.isDragOver = false;

        const files = event.dataTransfer?.files;
        if (files && files.length > 0) {
            const file = files[0];

            if (file.name.endsWith('.epub')) {
                this.selectedFile = file;
                this.errorMessage = '';
            } else {
                this.errorMessage = 'Загрузите файл с расширением .epub';
                this.selectedFile = null;
            }
        }
    }
}
