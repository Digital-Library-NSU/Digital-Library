import { CommonModule } from '@angular/common';
import { Component, inject, input, output, signal } from '@angular/core';
import { BookDataService } from '../../../../core/services/book-data.service';
import { Book } from '../../../../shared/models/book.model';
import { environment } from '../../../../../environments/environment';
import { BookReviewsComponent } from '../book-reviews/book-reviews.component';

@Component({
    selector: 'app-book-details-modal',
    imports: [CommonModule, BookReviewsComponent],
    templateUrl: './book-details-modal.component.html',
    styleUrl: './book-details-modal.component.scss',
})
export class BookDetailsModalComponent {
    book = input.required<Book | null>();
    close = output<void>();
    bookUpdated = output<Book>();

    private bookDataService = inject(BookDataService);
    protected readonly apiUrl = environment.apiUrl;

    refreshedBook = signal<Book | null>(null);

    get currentBook(): Book | null {
        return this.refreshedBook() ?? this.book();
    }

    closeModal() {
        this.close.emit();
    }

    onReviewsChanged() {
        const current = this.currentBook;
        if (!current) return;

        this.bookDataService.getBookById(current.book_id).subscribe({
            next: (fresh) => {
                this.refreshedBook.set(fresh);
                this.bookUpdated.emit(fresh);
            },
        });
    }
}
