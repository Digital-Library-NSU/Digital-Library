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

    // performSearch() {
    //     const query = this.searchQuery.trim();
    //     if (!query) {
    //         this.clear();
    //         return;
    //     }

    //     this.isSearching = true;
    //     this.searchStarted.emit();

    //     if (this.searchMode === 'fulltext') {
    //         const MOCK_RESPONSE = {
    //             total: 2,
    //             hits: [
    //                 {
    //                     book: {
    //                         book_id: 101,
    //                         title: 'Мастер и Маргарита',
    //                         cover_path: null,
    //                         authors: 'Михаил Булгаков',
    //                     },
    //                     score: 15.5,
    //                     match_type: 'quote',
    //                     snippet: {
    //                         doc_id: 'doc_1',
    //                         edition_id: 'ed_1',
    //                         chapter_ord: 12,
    //                         chapter_path: '/path',
    //                         chapter_title: 'Черная магия и ее разоблачение',
    //                         snippet:
    //                             'В этот момент <em>кот</em> отставил в сторону примус и вытащил из-за спины браунинг.',
    //                     },
    //                 },
    //                 {
    //                     book: {
    //                         book_id: 102,
    //                         title: 'Алиса в Стране чудес',
    //                         cover_path: null,
    //                         authors: 'Льюис Кэрролл',
    //                     },
    //                     score: 10.1,
    //                     match_type: 'meta',
    //                 },
    //             ],
    //         };

    //         of(MOCK_RESPONSE)
    //             .pipe(delay(1000))
    //             .subscribe({
    //                 next: (response: any) => {
    //                     this.isSearching = false;
    //                     this.searchResults.emit({
    //                         hits: response.hits,
    //                         total: response.total,
    //                     });
    //                 },
    //             });
    //     } else if (this.searchMode === 'semantic') {
    //         const MOCK_SEMANTIC_RESPONSE = {
    //             total: 50,
    //             hits: [
    //                 {
    //                     book: {
    //                         book_id: 42,
    //                         title: 'Физика для чайников',
    //                         cover_path: null,
    //                         authors: 'Иван Иванов',
    //                     },
    //                     score: 0.89,
    //                     snippet: {
    //                         doc_id: 'vec_1',
    //                         edition_id: '12',
    //                         chapter_ord: 10,
    //                         chapter_path: '/path',
    //                         chapter_title: 'Оптика',
    //                         snippet:
    //                             'Рэлеевское рассеяние объясняет цвет неба. Это происходит потому, что короткие волны рассеиваются сильнее.',
    //                     },
    //                 },
    //                 {
    //                     book: {
    //                         book_id: 88,
    //                         title: 'Энциклопедия моря',
    //                         cover_path: null,
    //                         authors: 'Жак-Ив Кусто',
    //                     },
    //                     score: 0.75,
    //                     snippet: {
    //                         doc_id: 'vec_2',
    //                         edition_id: '15',
    //                         chapter_ord: 2,
    //                         chapter_path: '/path',
    //                         chapter_title: 'Почему море синее?',
    //                         snippet:
    //                             'Вода поглощает цвета красной части спектра, поэтому отраженный свет кажется нам голубым или синим.',
    //                     },
    //                 },
    //             ],
    //         };

    //         of(MOCK_SEMANTIC_RESPONSE)
    //             .pipe(delay(800))
    //             .subscribe({
    //                 next: (response: any) => {
    //                     this.isSearching = false;
    //                     this.searchResults.emit({
    //                         hits: response.hits,
    //                         total: response.total,
    //                     });
    //                 },
    //             });
    //     }
    // }

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
