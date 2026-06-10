import { Injectable, inject, signal } from '@angular/core';
import { ApiService } from './api.service';
import {
    Bookmark,
    CreateBookmarkRequest,
} from '../../shared/models/bookmark.model';

@Injectable({
    providedIn: 'root',
})
export class BookmarkService {
    private api = inject(ApiService);

    readonly bookmarks = signal<Bookmark[]>([]);

    load(bookId: number): void {
        this.api.get<Bookmark[]>(`/bookmarks/${bookId}`).subscribe({
            next: (list) => this.bookmarks.set(list),
            error: () => this.bookmarks.set([]),
        });
    }

    add(bookId: number, chapterId: number, dataBlockIndex: number): void {
        const body: CreateBookmarkRequest = {
            chapter_id: chapterId,
            data_block_index: dataBlockIndex,
        };

        this.api.post<Bookmark>(`/bookmarks/${bookId}`, body).subscribe({
            next: (created) => {
                const exists = this.bookmarks().some(
                    (b) => b.bookmark_id === created.bookmark_id,
                );
                if (!exists) {
                    this.bookmarks.update((list) => [...list, created]);
                }
            },
        });
    }

    remove(bookId: number, bookmarkId: string): void {
        this.api.delete<void>(`/bookmarks/${bookId}/${bookmarkId}`).subscribe({
            next: () => {
                this.bookmarks.update((list) =>
                    list.filter((b) => b.bookmark_id !== bookmarkId),
                );
            },
        });
    }

    clear(): void {
        this.bookmarks.set([]);
    }
}
