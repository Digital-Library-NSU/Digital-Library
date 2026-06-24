import { CommonModule } from '@angular/common';
import { Component, EventEmitter, inject, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { of, finalize, delay } from 'rxjs';
import { BookDataService } from '../../../../core/services/book-data.service';
import { SearchHit } from '../../../../shared/models/book.model';

@Component({
    selector: 'app-search-widget',
    imports: [CommonModule, FormsModule],
    templateUrl: './search-widget.component.html',
    styleUrl: './search-widget.component.scss',
})
export class SearchWidgetComponent {
    private bookService = inject(BookDataService);

    @Output() searchResults = new EventEmitter<{
        hits: SearchHit[];
        total: number;
    }>();
    @Output() searchCleared = new EventEmitter<void>();
    @Output() searchStarted = new EventEmitter<void>();

    searchMode: 'fulltext' | 'semantic' = 'fulltext';
    searchQuery = '';
    isSearching = false;

    setSearchMode(mode: 'fulltext' | 'semantic') {
        this.searchMode = mode;
    }

    getPlaceholder() {
        return this.searchMode === 'fulltext'
            ? 'Поиск по названию, автору или цитате...'
            : 'Опишите, что вы хотите найти (e.g. "книга про погоду")...';
    }

    performSearch() {
        const query = this.searchQuery.trim();
        if (!query) {
            this.clear();
            return;
        }

        this.isSearching = true;
        this.searchStarted.emit();

        if (this.searchMode === 'fulltext') {
            this.bookService
                .searchFullText(query)
                .pipe(finalize(() => (this.isSearching = false)))
                .subscribe({
                    next: (response) => {
                        this.searchResults.emit({
                            hits: response.hits,
                            total: response.total,
                        });
                    },
                    error: (err) => console.error(err),
                });
        } else if (this.searchMode === 'semantic') {
            this.bookService
                .searchSemantic(query)
                .pipe(finalize(() => (this.isSearching = false)))
                .subscribe({
                    next: (response) => {
                        this.searchResults.emit({
                            hits: response.hits,
                            total: response.total,
                        });
                    },
                    error: (err) => console.error(err),
                });
        }
    }

    clear() {
        this.searchQuery = '';
        this.searchCleared.emit();
    }
}
