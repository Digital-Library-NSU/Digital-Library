import {
    Component,
    OnInit,
    OnDestroy,
    ViewChild,
    ElementRef,
    inject,
    ViewEncapsulation,
    HostListener,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { ReaderService } from '../../core/services/reader.service';
import {
    ChaptersList,
    InBookSearchHit,
} from '../../shared/models/reader.model';
import { Bookmark } from '../../shared/models/bookmark.model';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../core/services/auth.service';
import { BookmarkService } from '../../core/services/bookmark.service';
import { BookmarksPanelComponent } from './components/bookmarks-panel/bookmarks-panel.component';
import { GuestReadingProgressService } from '../../core/services/guest-reading-progress.service';
import {
    ReadingProgress,
    ReadingProgressService,
} from '../../core/services/reading-progress.service';

@Component({
    selector: 'app-reader',
    imports: [CommonModule, FormsModule, BookmarksPanelComponent],
    templateUrl: './reader.component.html',
    styleUrl: './reader.component.scss',
    encapsulation: ViewEncapsulation.None,
})
export class ReaderComponent implements OnInit, OnDestroy {
    private route = inject(ActivatedRoute);
    private router = inject(Router);
    private readerService = inject(ReaderService);
    private sanitizer = inject(DomSanitizer);
    private auth = inject(AuthService);
    private bookmarkService = inject(BookmarkService);
    private guestProgress = inject(GuestReadingProgressService);
    private readingProgress = inject(ReadingProgressService);

    readonly isAuthenticated = this.auth.isAuthenticated;

    @ViewChild('bookContainer') bookContainer!: ElementRef<HTMLDivElement>;

    bookId!: number;
    currentChapterId!: number;

    chaptersList: ChaptersList = { chapters: [] };
    currentChapterIndex = 0;

    safeContent: SafeHtml | null = null;
    isLoading = false;
    isSidebarOpen = false;
    isBookmarksPanelOpen = false;

    fontSize = 18;
    private readonly COLUMN_GAP = 80;
    private readonly SAVE_PROGRESS_DELAY_MS = 400;
    private progressSaveTimer: ReturnType<typeof setTimeout> | null = null;
    private pendingPageScrollLeft: number | null = null;
    private pendingPageScrollFrame: number | null = null;

    isSearchOpen = false;
    isSearching = false;
    searchQuery = '';
    searchResults: InBookSearchHit[] = [];

    ngOnInit() {
        this.bookId = Number(this.route.snapshot.paramMap.get('id'));
        const chapterParam = this.route.snapshot.paramMap.get('chapterId');

        if (this.isAuthenticated()) {
            this.bookmarkService.load(this.bookId);
        }

        this.loadTOC(chapterParam ? Number(chapterParam) : null);
    }

    ngOnDestroy() {
        this.saveReadingProgress();
        if (this.progressSaveTimer) {
            clearTimeout(this.progressSaveTimer);
        }
        if (this.pendingPageScrollFrame !== null) {
            cancelAnimationFrame(this.pendingPageScrollFrame);
        }
        this.bookmarkService.clear();
    }

    loadTOC(initialChapterId: number | null) {
        this.readerService.getAllChapters(this.bookId).subscribe({
            next: (data) => {
                this.chaptersList = data;
                this.loadInitialChapter(initialChapterId);
            },
            error: (err) => console.error('Failed to load TOC', err),
        });
    }

    private loadInitialChapter(initialChapterId: number | null) {
        if (this.route.snapshot.queryParamMap.get('restart') === 'true') {
            this.openInitialChapter(initialChapterId, null);
            return;
        }

        if (this.isAuthenticated()) {
            this.readingProgress.getAll().subscribe({
                next: (items) => {
                    const savedProgress =
                        items.find((item) => item.book_id === this.bookId) ??
                        null;
                    this.openInitialChapter(initialChapterId, savedProgress);
                },
                error: () => this.openInitialChapter(initialChapterId, null),
            });
            return;
        }

        this.openInitialChapter(
            initialChapterId,
            this.guestProgress.get(this.bookId),
        );
    }

    private openInitialChapter(
        initialChapterId: number | null,
        savedProgress:
            | ReadingProgress
            | { chapterId: number; dataBlockIndex: number; scrollLeft?: number }
            | null,
    ) {
        const savedChapterId =
            savedProgress && 'chapter_id' in savedProgress
                ? savedProgress.chapter_id
                : savedProgress?.chapterId;
        const requestedChapterId = savedChapterId ?? initialChapterId;

        if (requestedChapterId) {
            this.currentChapterIndex = this.chaptersList.chapters.findIndex(
                (c) => c.chapter_id === requestedChapterId,
            );
            if (this.currentChapterIndex === -1) this.currentChapterIndex = 0;
        } else {
            this.currentChapterIndex = 0;
        }

        this.loadChapter(
            this.chaptersList.chapters[this.currentChapterIndex].chapter_id,
            false,
            savedProgress
                ? () => this.restoreReadingProgress(savedProgress)
                : undefined,
        );
    }

    loadChapter(
        chapterId: number,
        scrollToEnd: boolean = false,
        onSuccess?: () => void,
    ) {
        this.isLoading = true;
        this.currentChapterId = chapterId;

        this.router.navigate(['/read', this.bookId, chapterId], {
            replaceUrl: true,
            queryParamsHandling: 'preserve',
        });

        this.readerService.getChapterContent(this.bookId, chapterId).subscribe({
            next: (html) => {
                this.safeContent = this.sanitizer.bypassSecurityTrustHtml(html);
                this.isLoading = false;

                requestAnimationFrame(() => {
                    if (this.bookContainer) {
                        const container = this.bookContainer.nativeElement;

                        if (scrollToEnd) {
                            const pageWidth = container.clientWidth;
                            const totalWidth = container.scrollWidth;
                            const totalPages = Math.ceil(
                                totalWidth / pageWidth,
                            );

                            const lastPageScrollPosition =
                                (totalPages - 1) * pageWidth;

                            container.scrollLeft = lastPageScrollPosition;
                        } else {
                            this.bookContainer.nativeElement.scrollLeft = 0;
                        }
                        if (onSuccess) {
                            // вызовется после рендера
                            onSuccess();
                        } else {
                            this.queueReadingProgressSave();
                        }
                    }
                });
            },
            error: (err) => {
                console.error(err);
                this.isLoading = false;
            },
        });
    }

    nextPage() {
        const container = this.bookContainer.nativeElement;
        const pageWidth = container.clientWidth;
        const currentScroll = container.scrollLeft + pageWidth;

        if (currentScroll < container.scrollWidth - 10) {
            this.scrollToPage(container.scrollLeft + pageWidth + this.COLUMN_GAP);
        } else {
            this.goToNextChapter();
        }
    }

    prevPage() {
        const container = this.bookContainer.nativeElement;
        const pageWidth = container.clientWidth;

        if (container.scrollLeft > 0) {
            this.scrollToPage(container.scrollLeft - (pageWidth + this.COLUMN_GAP));
        } else {
            this.goToPrevChapter();
        }
    }

    goToNextChapter() {
        if (this.currentChapterIndex < this.chaptersList.chapters.length - 1) {
            this.currentChapterIndex++;
            this.loadChapter(
                this.chaptersList.chapters[this.currentChapterIndex].chapter_id,
                false,
            );
        }
    }

    goToPrevChapter() {
        if (this.currentChapterIndex > 0) {
            this.currentChapterIndex--;
            this.loadChapter(
                this.chaptersList.chapters[this.currentChapterIndex].chapter_id,
                true,
            );
        }
    }

    toggleSearch() {
        this.isSearchOpen = !this.isSearchOpen;
    }

    performInBookSearch() {
        const query = this.searchQuery.trim();
        if (!query) return;

        this.isSearching = true;
        this.readerService.searchInBook(this.bookId, query).subscribe({
            next: (response) => {
                this.searchResults = response.hits;
                this.isSearching = false;
            },
            error: (err) => {
                console.error('Search error', err);
                this.isSearching = false;
            },
        });
    }

    goToSearchResult(hit: InBookSearchHit) {
        const snippet = hit.snippet;

        const targetIndex = this.chaptersList.chapters.findIndex(
            (chapter) => chapter.chapter_id === snippet.chapter_id,
        );

        if (targetIndex === -1) {
            console.error('Chapter not found for snippet', snippet);
            return;
        }

        const blockIndex = snippet.hit_block_index ?? snippet.block_start;

        if (blockIndex === null || blockIndex === undefined) {
            console.error('Block index not found for snippet', snippet);
            return;
        }

        if (this.currentChapterIndex === targetIndex) {
            this.scrollToBlock(blockIndex);
        } else {
            this.currentChapterIndex = targetIndex;
            const targetChapter = this.chaptersList.chapters[targetIndex];

            this.loadChapter(targetChapter.chapter_id, false, () => {
                this.scrollToBlock(blockIndex);
            });
        }

        this.isSearchOpen = false;
    }

    onReaderScroll() {
        this.queueReadingProgressSave();
    }

    private scrollToBlock(blockIndex: number) {
        setTimeout(() => {
            const container = this.bookContainer.nativeElement;

            const targetEl = container.querySelector(
                `[data-block-index="${blockIndex}"]`,
            ) as HTMLElement | null;

            if (!targetEl) {
                console.error('Target block not found', blockIndex);
                return;
            }

            const elementOffset = targetEl.offsetLeft;
            const pageWidth = container.clientWidth;
            const stride = pageWidth + this.COLUMN_GAP;

            const pageIndex = Math.floor(elementOffset / stride);

            container.scrollTo({
                left: pageIndex * stride,
                behavior: 'smooth',
            });
            this.queueReadingProgressSave();

            targetEl.classList.add('search-hit-highlight');

            setTimeout(() => {
                targetEl.classList.remove('search-hit-highlight');
            }, 2500);
        }, 150);
    }

    private restoreReadingProgress(
        progress:
            | ReadingProgress
            | { dataBlockIndex: number; scrollLeft?: number },
    ) {
        setTimeout(() => {
            const container = this.bookContainer?.nativeElement;
            if (!container) return;

            const maxScrollLeft = Math.max(
                0,
                container.scrollWidth - container.clientWidth,
            );

            if (this.isServerReadingProgress(progress)) {
                container.scrollLeft =
                    Math.max(0, Math.min(progress.chapter_scroll_ratio, 1)) *
                    maxScrollLeft;
                return;
            }

            if (
                progress.scrollLeft !== undefined &&
                progress.scrollLeft >= 0 &&
                progress.scrollLeft <= maxScrollLeft
            ) {
                container.scrollLeft = progress.scrollLeft;
                return;
            }

            this.scrollToBlock(progress.dataBlockIndex);
        }, 150);
    }

    private isServerReadingProgress(
        progress:
            | ReadingProgress
            | { dataBlockIndex: number; scrollLeft?: number },
    ): progress is ReadingProgress {
        return 'data_block_index' in progress;
    }

    toggleSidebar() {
        this.isSidebarOpen = !this.isSidebarOpen;
    }

    selectChapter(index: number) {
        this.currentChapterIndex = index;
        this.loadChapter(this.chaptersList.chapters[index].chapter_id);
        this.isSidebarOpen = false;
    }

    toggleBookmarksPanel() {
        this.isBookmarksPanelOpen = !this.isBookmarksPanelOpen;
    }

    private getCurrentBlockIndex(): number | null {
        return this.getCurrentReadingPosition()?.blockIndex ?? null;
    }

    private getCurrentReadingPosition(): {
        blockIndex: number;
        blockCharOffset: number;
        chapterScrollRatio: number;
    } | null {
        if (!this.bookContainer) return null;

        const container = this.bookContainer.nativeElement;
        const containerRect = container.getBoundingClientRect();
        const target = this.findFirstVisibleBlock(container, containerRect);

        if (!target) return null;

        const raw = target.getAttribute('data-block-index');
        if (raw === null) return null;

        const blockIndex = Number(raw);
        if (!Number.isFinite(blockIndex)) return null;

        const maxScrollLeft = Math.max(
            0,
            container.scrollWidth - container.clientWidth,
        );

        return {
            blockIndex,
            blockCharOffset: this.findFirstVisibleCharOffset(
                target,
                containerRect,
            ),
            chapterScrollRatio:
                maxScrollLeft > 0 ? container.scrollLeft / maxScrollLeft : 0,
        };
    }

    private findFirstVisibleBlock(
        container: HTMLElement,
        containerRect: DOMRect,
    ): HTMLElement | null {
        const yStart = containerRect.top + 8;
        const yEnd = containerRect.bottom - 8;

        const primaryXPositions = [
            containerRect.left + 16,
            containerRect.left + containerRect.width * 0.25,
            containerRect.left + containerRect.width * 0.5,
            containerRect.left + containerRect.width * 0.75,
            containerRect.right - 16,
        ];

        for (let y = yStart; y <= yEnd; y += 6) {
            for (const x of primaryXPositions) {
                const block = this.blockFromPoint(x, y, container);
                if (block) return block;
            }
        }

        const xStart = containerRect.left + 8;
        const xEnd = containerRect.right - 8;
        const xStep = Math.max(12, Math.floor(containerRect.width / 24));

        for (let y = yStart; y <= yEnd; y += 8) {
            for (let x = xStart; x <= xEnd; x += xStep) {
                const block = this.blockFromPoint(x, y, container);
                if (block) return block;
            }
        }

        return null;
    }

    private blockFromPoint(
        x: number,
        y: number,
        container: HTMLElement,
    ): HTMLElement | null {
        const el = document.elementFromPoint(x, y);
        const block = el?.closest?.('[data-block-index]');

        return block instanceof HTMLElement && container.contains(block)
            ? block
            : null;
    }

    private findFirstVisibleCharOffset(
        block: HTMLElement,
        containerRect: DOMRect,
    ): number {
        const pointOffset = this.findTextOffsetAtPoint(block, containerRect);
        if (pointOffset !== null) return pointOffset;

        const textNodes = this.getTextNodes(block);
        let blockOffset = 0;

        for (const node of textNodes) {
            const visibleOffset = this.findFirstVisibleOffsetInTextNode(
                node,
                containerRect,
            );

            if (visibleOffset !== null) {
                return blockOffset + visibleOffset;
            }

            blockOffset += node.textContent?.length ?? 0;
        }

        return 0;
    }

    private findTextOffsetAtPoint(
        block: HTMLElement,
        containerRect: DOMRect,
    ): number | null {
        const doc = document as Document & {
            caretPositionFromPoint?: (
                x: number,
                y: number,
            ) => { offsetNode: Node; offset: number } | null;
            caretRangeFromPoint?: (x: number, y: number) => Range | null;
        };

        const x = containerRect.left + 8;
        const y = containerRect.top + 8;
        let node: Node | null = null;
        let offset: number | null = null;

        const caretPosition = doc.caretPositionFromPoint?.(x, y);
        if (caretPosition) {
            node = caretPosition.offsetNode;
            offset = caretPosition.offset;
        } else {
            const range = doc.caretRangeFromPoint?.(x, y);
            if (range) {
                node = range.startContainer;
                offset = range.startOffset;
            }
        }

        if (
            !node ||
            offset === null ||
            node.nodeType !== Node.TEXT_NODE ||
            !block.contains(node)
        ) {
            return null;
        }

        return this.getOffsetFromBlockStart(block, node as Text, offset);
    }

    private getOffsetFromBlockStart(
        block: HTMLElement,
        targetNode: Text,
        targetOffset: number,
    ): number {
        let offset = 0;

        for (const node of this.getTextNodes(block)) {
            if (node === targetNode) {
                return offset + targetOffset;
            }

            offset += node.textContent?.length ?? 0;
        }

        return 0;
    }

    private getTextNodes(root: Node): Text[] {
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        const nodes: Text[] = [];

        while (walker.nextNode()) {
            const node = walker.currentNode as Text;
            if (node.textContent?.trim()) {
                nodes.push(node);
            }
        }

        return nodes;
    }

    private findFirstVisibleOffsetInTextNode(
        node: Text,
        containerRect: DOMRect,
    ): number | null {
        const length = node.textContent?.length ?? 0;
        const step = 16;

        for (let offset = 0; offset < length; offset += step) {
            if (!this.isTextOffsetVisible(node, offset, containerRect)) {
                continue;
            }

            const start = Math.max(0, offset - step + 1);
            for (let exact = start; exact <= offset; exact++) {
                if (this.isTextOffsetVisible(node, exact, containerRect)) {
                    return exact;
                }
            }

            return offset;
        }

        return null;
    }

    private isTextOffsetVisible(
        node: Text,
        offset: number,
        containerRect: DOMRect,
    ): boolean {
        if (!node.textContent || offset >= node.textContent.length) {
            return false;
        }

        const range = document.createRange();
        range.setStart(node, offset);
        range.setEnd(node, Math.min(offset + 1, node.textContent.length));

        const rects = Array.from(range.getClientRects());
        range.detach();

        return rects.some(
            (rect) =>
                rect.right > containerRect.left &&
                rect.left < containerRect.right &&
                rect.bottom > containerRect.top &&
                rect.top < containerRect.bottom,
        );
    }

    private findBookmarkAtCurrent(): Bookmark | undefined {
        const blockIndex = this.getCurrentBlockIndex();
        if (blockIndex === null) return undefined;

        return this.bookmarkService
            .bookmarks()
            .find(
                (b) =>
                    b.chapter_id === this.currentChapterId &&
                    b.data_block_index === blockIndex,
            );
    }

    get isCurrentBlockBookmarked(): boolean {
        return this.findBookmarkAtCurrent() !== undefined;
    }

    toggleBookmarkAtCurrent() {
        const existing = this.findBookmarkAtCurrent();

        if (existing) {
            this.bookmarkService.remove(this.bookId, existing.bookmark_id);
            return;
        }

        const blockIndex = this.getCurrentBlockIndex();
        if (blockIndex === null) return;

        this.bookmarkService.add(
            this.bookId,
            this.currentChapterId,
            blockIndex,
        );
    }

    goToBookmark(bookmark: Bookmark) {
        const targetIndex = this.chaptersList.chapters.findIndex(
            (chapter) => chapter.chapter_id === bookmark.chapter_id,
        );

        if (targetIndex === -1) {
            console.error('Chapter not found for bookmark', bookmark);
            return;
        }

        if (this.currentChapterIndex === targetIndex) {
            this.scrollToBlock(bookmark.data_block_index);
        } else {
            this.currentChapterIndex = targetIndex;
            this.loadChapter(bookmark.chapter_id, false, () => {
                this.scrollToBlock(bookmark.data_block_index);
            });
        }

        this.isBookmarksPanelOpen = false;
    }

    private queueReadingProgressSave() {
        if (this.pendingPageScrollLeft !== null) return;

        if (this.progressSaveTimer) {
            clearTimeout(this.progressSaveTimer);
        }

        this.progressSaveTimer = setTimeout(() => {
            this.saveReadingProgress();
        }, this.SAVE_PROGRESS_DELAY_MS);
    }

    private scrollToPage(targetScrollLeft: number) {
        const container = this.bookContainer.nativeElement;
        const maxScrollLeft = Math.max(
            0,
            container.scrollWidth - container.clientWidth,
        );
        const target = Math.max(0, Math.min(targetScrollLeft, maxScrollLeft));

        this.pendingPageScrollLeft = target;

        if (this.progressSaveTimer) {
            clearTimeout(this.progressSaveTimer);
            this.progressSaveTimer = null;
        }
        if (this.pendingPageScrollFrame !== null) {
            cancelAnimationFrame(this.pendingPageScrollFrame);
        }

        container.scrollTo({
            left: target,
            behavior: 'smooth',
        });

        this.waitForPageScrollToSettle(target, container.scrollLeft, 0);
    }

    private waitForPageScrollToSettle(
        target: number,
        lastScrollLeft: number,
        stableFrames: number,
    ) {
        this.pendingPageScrollFrame = requestAnimationFrame(() => {
            const container = this.bookContainer?.nativeElement;
            if (!container) return;

            const current = container.scrollLeft;
            const reachedTarget = Math.abs(current - target) <= 2;
            const stopped = Math.abs(current - lastScrollLeft) <= 0.5;
            const nextStableFrames = stopped ? stableFrames + 1 : 0;

            if (reachedTarget || nextStableFrames >= 6) {
                this.pendingPageScrollLeft = null;
                this.pendingPageScrollFrame = null;
                this.saveReadingProgress();
                return;
            }

            this.waitForPageScrollToSettle(target, current, nextStableFrames);
        });
    }

    private saveReadingProgress() {
        const position = this.getCurrentReadingPosition();
        const container = this.bookContainer?.nativeElement;

        if (!position) {
            return;
        }

        if (this.isAuthenticated()) {
            const payload = {
                book_id: this.bookId,
                chapter_id: this.currentChapterId,
                data_block_index: position.blockIndex,
                block_char_offset: position.blockCharOffset,
                chapter_scroll_ratio: position.chapterScrollRatio,
                is_completed: this.isAtEndOfBook(),
            };

            this.readingProgress
                .set(payload)
                .subscribe({ error: (err) => console.error(err) });
        } else {
            this.guestProgress.set({
                bookId: this.bookId,
                chapterId: this.currentChapterId,
                dataBlockIndex: position.blockIndex,
                scrollLeft: this.bookContainer.nativeElement.scrollLeft,
            });
        }
    }

    private isAtEndOfBook(): boolean {
        const container = this.bookContainer?.nativeElement;
        if (!container) return false;

        const isLastChapter =
            this.currentChapterIndex === this.chaptersList.chapters.length - 1;
        const maxScrollLeft = Math.max(
            0,
            container.scrollWidth - container.clientWidth,
        );
        const isLastPage = container.scrollLeft >= maxScrollLeft - 2;

        return isLastChapter && isLastPage;
    }

    @HostListener('window:keydown', ['$event'])
    handleKeyboard(event: KeyboardEvent) {
        if (event.key === 'ArrowRight') this.nextPage();
        if (event.key === 'ArrowLeft') this.prevPage();
    }

    @HostListener('window:beforeunload')
    handleBeforeUnload() {
        this.saveReadingProgress();
    }

    exitReader() {
        this.router.navigateByUrl(
            this.route.snapshot.queryParamMap.get('returnUrl') ?? '/',
            {
                replaceUrl: true,
            },
        );
    }
}
