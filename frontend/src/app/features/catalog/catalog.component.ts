import { CommonModule } from '@angular/common';
import { Component, inject, NgZone, OnDestroy } from '@angular/core';
import { BookCardComponent } from './components/book-card/book-card.component';
import { Book, BookCard, SearchHit } from '../../shared/models/book.model';
import {
    BookDataService,
    BooksSortMode,
    CancelImportResponse,
    ImportTaskStatus,
    UploadBookResponse,
} from '../../core/services/book-data.service';
import { finalize } from 'rxjs/operators';
import { BookDetailsModalComponent } from './components/book-details-modal/book-details-modal.component';
import { UploadBookModalComponent } from './components/upload-book-modal/upload-book-modal.component';
import { SearchWidgetComponent } from './components/search-widget/search-widget.component';
import { SearchResultsComponent } from './components/search-results/search-results.component';
import { AuthService } from '../../core/services/auth.service';

interface ImportToast extends ImportTaskStatus {
    canceling?: boolean;
}

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
export class CatalogComponent implements OnDestroy {
    private bookService = inject(BookDataService);
    private auth = inject(AuthService);
    private zone = inject(NgZone);
    private readonly sortModeStorageKey = 'catalogSortMode';
    private readonly importToastsStorageKey = 'catalogImportToasts';
    private importEvents: EventSource | null = null;
    private importEventsKey = '';

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
    importToasts: ImportToast[] = [];

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
        this.restoreImportToasts();
        this.loadBooks();
    }

    ngOnDestroy() {
        this.closeImportEvents();
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

    onBookDeleted(bookId: number) {
        this.books = this.books.filter((book) => book.book_id !== bookId);
        this.selectedBook = null;

        if (this.viewMode === 'search') {
            this.searchResults = this.searchResults.filter(
                (hit) => hit.book.book_id !== bookId,
            );
            this.searchTotal = Math.max(0, this.searchTotal - 1);
        }
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

    onUploadQueued(response: UploadBookResponse) {
        const toast: ImportToast = {
            task_id: response.task_id,
            state: 'PENDING',
            filename: response.filename ?? null,
            stage: 'queued',
            status_label: 'Книга в очереди',
            progress_percent: 0,
            queued: true,
        };

        this.importToasts.push(toast);
        this.storeImportToasts();
        this.refreshImportEvents();
    }

    closeImportToast(taskId: string) {
        this.importToasts = this.importToasts.filter(
            (item) => item.task_id !== taskId,
        );
        this.storeImportToasts();
        this.refreshImportEvents();
    }

    cancelImportToast(taskId: string) {
        const toast = this.importToasts.find((item) => item.task_id === taskId);
        if (!toast || this.canCloseImportToast(toast) || toast.canceling) return;

        toast.canceling = true;
        toast.status_label = 'Отменяем импорт';
        this.storeImportToasts();
        this.refreshImportEvents();

        this.bookService.cancelImport(taskId).subscribe({
            next: (response) => this.markImportCancelled(toast, response),
            error: (err) => {
                console.error(err);
                toast.canceling = false;
                toast.status_label = 'Не удалось отменить импорт';
                toast.error = 'Попробуйте отменить еще раз или перезапустить очередь импортов';
                this.storeImportToasts();
                this.refreshImportEvents();
            },
        });
    }

    importTitle(toast: ImportToast): string {
        return toast.title || toast.filename || 'Книга';
    }

    importAuthors(toast: ImportToast): string {
        return toast.authors || 'Автор уточняется';
    }

    importProgress(toast: ImportToast): number {
        return Math.max(
            0,
            Math.min(100, Math.round(toast.progress_percent ?? 0)),
        );
    }

    hasImportProgress(toast: ImportToast): boolean {
        return toast.progress_percent !== null && toast.progress_percent !== undefined;
    }

    shouldShowImportProgress(toast: ImportToast): boolean {
        return !this.canCloseImportToast(toast);
    }

    importCounter(toast: ImportToast): string {
        if (toast.current === null || toast.current === undefined) return '';
        if (toast.total === null || toast.total === undefined) return '';

        const unit = toast.unit === 'windows'
            ? 'фрагментов'
            : toast.unit === 'documents'
              ? 'документов'
              : toast.unit === 'files'
                ? 'файлов'
                : toast.unit || '';

        return `${toast.current} / ${toast.total} ${unit}`;
    }

    canCloseImportToast(toast: ImportToast): boolean {
        return (
            toast.state === 'SUCCESS' ||
            toast.state === 'FAILURE' ||
            toast.state === 'REVOKED' ||
            toast.stage === 'completed' ||
            toast.stage === 'failed' ||
            toast.stage === 'cancelled'
        );
    }

    canCancelImportToast(toast: ImportToast): boolean {
        return !this.canCloseImportToast(toast) && !toast.canceling;
    }

    private markImportCancelled(toast: ImportToast, response: CancelImportResponse) {
        const fallbackFilename = toast.filename;
        Object.assign(toast, response);
        toast.filename = toast.filename || fallbackFilename;
        toast.queued = false;
        toast.progress_percent = null;
        toast.canceling = false;
        toast.error = null;
        this.storeImportToasts();
        this.refreshImportEvents();
    }

    private restoreImportToasts() {
        const raw = sessionStorage.getItem(this.importToastsStorageKey);
        if (!raw) return;

        try {
            const stored = JSON.parse(raw) as ImportTaskStatus[];
            this.importToasts = stored.map((item) => ({ ...item }));
            this.refreshImportEvents();
        } catch {
            sessionStorage.removeItem(this.importToastsStorageKey);
        }
    }

    private storeImportToasts() {
        const stored = this.importToasts.map((toast) => ({ ...toast }));
        sessionStorage.setItem(
            this.importToastsStorageKey,
            JSON.stringify(stored),
        );
    }

    private activeImportTaskIds(): string[] {
        return this.importToasts
            .filter((toast) => !this.canCloseImportToast(toast) && !toast.canceling)
            .map((toast) => toast.task_id)
            .sort();
    }

    private refreshImportEvents() {
        const taskIds = this.activeImportTaskIds();
        const nextKey = taskIds.join(',');

        if (nextKey === this.importEventsKey) return;

        this.closeImportEvents();
        this.importEventsKey = nextKey;

        if (taskIds.length === 0) return;

        const events = new EventSource(this.bookService.getImportEventsUrl(taskIds));
        this.importEvents = events;

        events.addEventListener('import-status', (event) => {
            this.zone.run(() => {
                const status = JSON.parse((event as MessageEvent).data) as ImportTaskStatus;
                this.applyImportStatus(status);
            });
        });

        events.onerror = (err) => {
            console.error('Import status stream error', err);
        };
    }

    private closeImportEvents() {
        this.importEvents?.close();
        this.importEvents = null;
        this.importEventsKey = '';
    }

    private applyImportStatus(status: ImportTaskStatus) {
        const toast = this.importToasts.find((item) => item.task_id === status.task_id);
        if (!toast) return;

        const fallbackFilename = toast.filename;
        const fallbackTitle = toast.title;
        const fallbackAuthors = toast.authors;

        Object.assign(toast, status);
        toast.filename = toast.filename || fallbackFilename;
        toast.title = toast.title || fallbackTitle;
        toast.authors = toast.authors || fallbackAuthors;
        toast.canceling = false;
        this.storeImportToasts();

        if (status.state === 'SUCCESS') {
            this.offset = 0;
            this.loadBooks();
        }

        if (this.canCloseImportToast(toast)) {
            this.refreshImportEvents();
        }
    }
}
