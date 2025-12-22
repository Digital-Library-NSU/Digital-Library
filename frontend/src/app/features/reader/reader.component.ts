import {
    Component,
    OnInit,
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
import { Chapter, ChaptersList } from '../../shared/models/reader.model';

@Component({
    selector: 'app-reader',
    imports: [CommonModule],
    templateUrl: './reader.component.html',
    styleUrl: './reader.component.scss',
    encapsulation: ViewEncapsulation.None,
})
export class ReaderComponent implements OnInit {
    private route = inject(ActivatedRoute);
    private router = inject(Router);
    private readerService = inject(ReaderService);
    private sanitizer = inject(DomSanitizer);

    @ViewChild('bookContainer') bookContainer!: ElementRef<HTMLDivElement>;

    bookId!: number;
    currentChapterId!: number;

    chaptersList: ChaptersList = { chapters: [] };
    currentChapterIndex = 0;

    safeContent: SafeHtml | null = null;
    isLoading = false;
    isSidebarOpen = false;

    fontSize = 18;

    ngOnInit() {
        this.bookId = Number(this.route.snapshot.paramMap.get('id'));
        const chapterParam = this.route.snapshot.paramMap.get('chapterId');

        this.loadTOC(chapterParam ? Number(chapterParam) : null);
    }

    loadTOC(initialChapterId: number | null) {
        this.readerService.getAllChapters(this.bookId).subscribe({
            next: (data) => {
                this.chaptersList = data;

                if (initialChapterId) {
                    this.currentChapterIndex =
                        this.chaptersList.chapters.findIndex(
                            (c) => c.chapter_id === initialChapterId
                        );
                    if (this.currentChapterIndex === -1)
                        this.currentChapterIndex = 0;
                } else {
                    this.currentChapterIndex = 0;
                }

                this.loadChapter(
                    this.chaptersList.chapters[this.currentChapterIndex]
                        .chapter_id
                );
            },
            error: (err) => console.error('Failed to load TOC', err),
        });
    }

    loadChapter(chapterId: number, scrollToEnd: boolean = false) {
        this.isLoading = true;
        this.currentChapterId = chapterId;

        this.router.navigate(['/read', this.bookId, chapterId], {
            replaceUrl: true,
        });

        this.readerService.getChapterContent(this.bookId, chapterId).subscribe({
            next: (html) => {
                this.safeContent = this.sanitizer.bypassSecurityTrustHtml(html);
                this.isLoading = false;

                requestAnimationFrame(() => {
                    if (this.bookContainer) {
                        const container = this.bookContainer.nativeElement;
                        const pageWidth = container.clientWidth;
                        const totalWidth = container.scrollWidth;

                        if (scrollToEnd) {
                            const totalPages = Math.ceil(
                                totalWidth / pageWidth
                            );

                            const lastPageScrollPosition =
                                (totalPages - 1) * pageWidth;

                            container.scrollLeft = lastPageScrollPosition;
                        } else {
                            this.bookContainer.nativeElement.scrollLeft = 0;
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
            container.scrollBy({ left: pageWidth + 80, behavior: 'smooth' });
        } else {
            this.goToNextChapter();
        }
    }

    prevPage() {
        const container = this.bookContainer.nativeElement;
        const pageWidth = container.clientWidth;

        if (container.scrollLeft > 0) {
            container.scrollBy({ left: -(pageWidth + 80), behavior: 'smooth' });
        } else {
            this.goToPrevChapter();
        }
    }

    goToNextChapter() {
        if (this.currentChapterIndex < this.chaptersList.chapters.length - 1) {
            this.currentChapterIndex++;
            this.loadChapter(
                this.chaptersList.chapters[this.currentChapterIndex].chapter_id,
                false
            );
        }
    }

    goToPrevChapter() {
        if (this.currentChapterIndex > 0) {
            this.currentChapterIndex--;
            this.loadChapter(
                this.chaptersList.chapters[this.currentChapterIndex].chapter_id,
                true
            );
        }
    }

    toggleSidebar() {
        this.isSidebarOpen = !this.isSidebarOpen;
    }

    selectChapter(index: number) {
        this.currentChapterIndex = index;
        this.loadChapter(this.chaptersList.chapters[index].chapter_id);
        this.isSidebarOpen = false;
    }

    @HostListener('window:keydown', ['$event'])
    handleKeyboard(event: KeyboardEvent) {
        if (event.key === 'ArrowRight') this.nextPage();
        if (event.key === 'ArrowLeft') this.prevPage();
    }

    exitReader() {
        this.router.navigate([''], {
            replaceUrl: true,
        });
    }
}
