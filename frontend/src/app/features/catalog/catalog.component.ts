import { CommonModule } from '@angular/common';
import { Component, inject } from '@angular/core';
import { BookCardComponent } from './components/book-card/book-card.component';
import { Book, BookCard } from '../../shared/models/book.model';
import { BookDataService } from '../../core/services/book-data.service';
import { finalize } from 'rxjs/operators';
import { BookDetailsModalComponent } from './components/book-details-modal/book-details-modal.component';
import { UploadBookModalComponent } from './components/upload-book-modal/upload-book-modal.component';

@Component({
    selector: 'app-catalog',
    imports: [
        CommonModule,
        BookCardComponent,
        BookDetailsModalComponent,
        UploadBookModalComponent,
    ],
    templateUrl: './catalog.component.html',
    styleUrl: './catalog.component.scss',
})
export class CatalogComponent {
    private bookService = inject(BookDataService);

    books: BookCard[] = [];
    isLoading = true;
    error = '';
    selectedBook: Book | null = null;
    isDetailsLoading = false;
    showUploadModal = false;

    limit = 12;
    offset = 0;

    ngOnInit() {
        this.loadBooks();
    }

    loadBooks() {
        this.isLoading = true;
        this.error = '';

        this.bookService
            .getAllBooks(this.limit, this.offset)
            .pipe(finalize(() => (this.isLoading = false)))
            .subscribe({
                next: (response) => {
                    this.books = response;
                },
                error: (err) => {
                    console.error(err);
                    this.error = 'Failed to load books';
                },
            });
    }

    openBookDetails(bookId: number) {
        this.isDetailsLoading = true;

        this.bookService
            .getBookById(bookId)
            .pipe(finalize(() => (this.isDetailsLoading = false)))
            .subscribe({
                next: (details) => {
                    this.selectedBook = details;
                },
                error: (err) => console.error('Error fetching details', err),
            });
    }

    closeDetails() {
        this.selectedBook = null;
    }

    openUploadModal() {
        this.showUploadModal = true;
    }

    closeUploadModal(shouldRefresh: boolean) {
        this.showUploadModal = false;
        if (shouldRefresh) {
            this.offset = 0;
            this.loadBooks();
        }
    }
}
