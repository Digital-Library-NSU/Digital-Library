import { CommonModule } from '@angular/common';
import { Component, inject } from '@angular/core';
import { BookCardComponent } from './components/book-card/book-card.component';
import { Book, BookCard, SearchHit } from '../../shared/models/book.model';
import {
    BookDataService,
    BooksSortMode,
} from '../../core/services/book-data.service';
import { finalize } from 'rxjs/operators';
import { BookDetailsModalComponent } from './components/book-details-modal/book-details-modal.component';
import { UploadBookModalComponent } from './components/upload-book-modal/upload-book-modal.component';
import { SearchWidgetComponent } from './components/search-widget/search-widget.component';
import { SearchResultsComponent } from './components/search-results/search-results.component';
import { AuthService } from '../../core/services/auth.service';

@Component({
    selector: 'app-catalog',
    imports: [
        CommonModule,
        BookCardComponent,
        BookDetailsModalComponent,
        UploadBookModalComponent,
        SearchWidgetComponent,
        SearchResultsComponent,
    ],
    templateUrl: './catalog.component.html',
    styleUrl: './catalog.component.scss',
})
export class CatalogComponent {
    private bookService = inject(BookDataService);
    private auth = inject(AuthService);
    private readonly sortModeStorageKey = 'catalogSortMode';

    readonly isAdmin = this.auth.isAdmin;
    readonly isAuthenticated = this.auth.isAuthenticated;

    books: BookCard[] = [];
    isLoading = true;
    error = '';
    selectedBook: Book | null = null;
    isDetailsLoading = false;
    showUploadModal = false;
    viewMode: 'default' | 'search' = 'default';
    searchResults: SearchHit[] = [];
    searchTotal = 0;

    limit = 12;
    offset = 0;
    sortMode: BooksSortMode = this.getStoredSortMode();

    get sortOptions(): { value: BooksSortMode; label: string }[] {
        const options: { value: BooksSortMode; label: string }[] = [
            { value: 'popular', label: 'Сначала популярные' },
            { value: 'new', label: 'Сначала новые' },
        ];

        if (this.isAuthenticated()) {
            options.push({ value: 'recommended', label: 'Рекомендации' });
        }

        return options;
    }

    ngOnInit() {
        this.loadBooks();
    }

    loadBooks() {
        if (this.sortMode === 'recommended' && !this.isAuthenticated()) {
            this.sortMode = 'popular';
            this.storeSortMode(this.sortMode);
        }

        this.isLoading = true;
        this.error = '';

        this.bookService
            .getAllBooks(this.limit, this.offset, this.sortMode)
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

    onSortModeChanged(value: string) {
        const nextMode = value as BooksSortMode;
        if (nextMode === 'recommended' && !this.isAuthenticated()) return;

        this.sortMode = nextMode;
        this.storeSortMode(nextMode);
        this.offset = 0;
        this.loadBooks();
    }

    private getStoredSortMode(): BooksSortMode {
        const stored = sessionStorage.getItem(this.sortModeStorageKey);

        if (
            stored === 'popular' ||
            stored === 'new' ||
            stored === 'recommended'
        ) {
            return stored;
        }

        return 'popular';
    }

    private storeSortMode(mode: BooksSortMode) {
        sessionStorage.setItem(this.sortModeStorageKey, mode);
    }

    onSearchResults(data: { hits: SearchHit[]; total: number }) {
        this.searchResults = data.hits;
        this.searchTotal = data.total;
        this.viewMode = 'search';
    }

    onSearchCleared() {
        this.viewMode = 'default';
        this.searchResults = [];
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

    onBookUpdated(updated: Book) {
        this.books = this.books.map((book) =>
            book.book_id === updated.book_id
                ? {
                      ...book,
                      avg_rating: updated.avg_rating,
                      reviews_count: updated.reviews_count,
                  }
                : book
        );
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
