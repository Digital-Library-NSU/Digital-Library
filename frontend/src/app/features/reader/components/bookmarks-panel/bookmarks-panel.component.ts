import { CommonModule } from '@angular/common';
import { Component, computed, inject, input, output } from '@angular/core';
import { BookmarkService } from '../../../../core/services/bookmark.service';
import { Bookmark } from '../../../../shared/models/bookmark.model';
import { Chapter } from '../../../../shared/models/reader.model';

interface BookmarkView extends Bookmark {
    chapterTitle: string;
}

@Component({
    selector: 'app-bookmarks-panel',
    imports: [CommonModule],
    templateUrl: './bookmarks-panel.component.html',
    styleUrl: './bookmarks-panel.component.scss',
})
export class BookmarksPanelComponent {
    bookId = input.required<number>();
    chapters = input.required<Chapter[]>();
    isOpen = input<boolean>(false);

    close = output<void>();
    navigate = output<Bookmark>();

    private bookmarkService = inject(BookmarkService);

    readonly items = computed<BookmarkView[]>(() => {
        const titleById = new Map(
            this.chapters().map((c) => [c.chapter_id, c.title])
        );

        return this.bookmarkService
            .bookmarks()
            .map((bm) => ({
                ...bm,
                chapterTitle:
                    titleById.get(bm.chapter_id) ?? `Глава ${bm.chapter_id}`,
            }))
            .sort(
                (a, b) =>
                    a.chapter_id - b.chapter_id ||
                    a.data_block_index - b.data_block_index
            );
    });

    onNavigate(bookmark: Bookmark) {
        this.navigate.emit(bookmark);
    }

    onDelete(event: Event, bookmark: Bookmark) {
        event.stopPropagation();
        this.bookmarkService.remove(this.bookId(), bookmark.bookmark_id);
    }

    closePanel() {
        this.close.emit();
    }
}
