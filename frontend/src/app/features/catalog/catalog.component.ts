import { CommonModule } from '@angular/common';
import { Component, inject } from '@angular/core';
import { BookCardComponent } from './components/book-card/book-card.component';
import { BookCard } from '../../shared/models/book.model';
import { BookDataService } from '../../core/services/book-data.service';
import { finalize } from 'rxjs/operators';

@Component({
    selector: 'app-catalog',
    imports: [CommonModule, BookCardComponent],
    templateUrl: './catalog.component.html',
    styleUrl: './catalog.component.scss',
})
export class CatalogComponent {
    private bookService = inject(BookDataService);

    books: BookCard[] = [];
    isLoading = true;
    error = '';

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
}
