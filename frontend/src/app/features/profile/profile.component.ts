import { CommonModule } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { Observable, finalize } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { ProfileService } from '../../core/services/profile.service';
import {
    ProfileReadingBook,
    ProfileReview,
} from '../../shared/models/profile.model';
import { environment } from '../../../environments/environment';
import { HeaderComponent } from '../../layouts/header/header/header.component';
import { BookDataService } from '../../core/services/book-data.service';
import { Book } from '../../shared/models/book.model';
import { BookDetailsModalComponent } from '../catalog/components/book-details-modal/book-details-modal.component';
import { ReviewFormComponent } from '../catalog/components/book-reviews/components/review-form/review-form.component';
import { ReviewItemComponent } from '../catalog/components/book-reviews/components/review-item/review-item.component';
import { Review } from '../../shared/models/review.model';
import { ReviewService } from '../../core/services/review.service';

type ProfileTab = 'reading' | 'finished' | 'reviews';

@Component({
    selector: 'app-profile',
    imports: [
        CommonModule,
        HeaderComponent,
        BookDetailsModalComponent,
        ReviewFormComponent,
        ReviewItemComponent,
    ],
    templateUrl: './profile.component.html',
    styleUrl: './profile.component.scss',
})
export class ProfileComponent implements OnInit {
    private auth = inject(AuthService);
    private profileService = inject(ProfileService);
    private bookDataService = inject(BookDataService);
    private reviewService = inject(ReviewService);
    private route = inject(ActivatedRoute);
    private router = inject(Router);

    protected readonly apiUrl = environment.apiUrl;
    readonly user = this.auth.user;

    activeTab = signal<ProfileTab>('reading');
    isLoading = signal(false);
    error = signal('');

    reading = signal<ProfileReadingBook[]>([]);
    finished = signal<ProfileReadingBook[]>([]);
    reviews = signal<ProfileReview[]>([]);
    selectedBook = signal<Book | null>(null);
    isDetailsLoading = signal(false);
    editingReviewId = signal<number | null>(null);

    private loadedTabs = new Set<ProfileTab>();

    ngOnInit() {
        const tab = this.route.snapshot.queryParamMap.get('tab');
        this.selectTab(this.isProfileTab(tab) ? tab : 'reading', false);
    }

    selectTab(tab: ProfileTab, updateUrl = true) {
        this.activeTab.set(tab);

        if (updateUrl) {
            this.router.navigate(['/profile'], {
                queryParams: { tab },
                replaceUrl: true,
            });
        }

        if (this.loadedTabs.has(tab)) return;

        this.loadTab(tab);
    }

    private isProfileTab(tab: string | null): tab is ProfileTab {
        return tab === 'reading' || tab === 'finished' || tab === 'reviews';
    }

    private getProfileReturnUrl(): string {
        return `/profile?tab=${this.activeTab()}`;
    }

    private loadTab(tab: ProfileTab) {
        this.isLoading.set(true);
        this.error.set('');

        const request: Observable<ProfileReadingBook[] | ProfileReview[]> =
            tab === 'reading'
                ? this.profileService.getReading()
                : tab === 'finished'
                  ? this.profileService.getFinished()
                  : this.profileService.getReviews();

        request.pipe(finalize(() => this.isLoading.set(false))).subscribe({
            next: (items) => {
                if (tab === 'reading') {
                    this.reading.set(items as ProfileReadingBook[]);
                } else if (tab === 'finished') {
                    this.finished.set(items as ProfileReadingBook[]);
                } else {
                    this.reviews.set(items as ProfileReview[]);
                }

                this.loadedTabs.add(tab);
            },
            error: (err) => {
                console.error(err);
                this.error.set('Не удалось загрузить данные профиля');
            },
        });
    }

    continueBook(item: ProfileReadingBook) {
        this.router.navigate(['/read', item.book.book_id, item.chapter_id], {
            queryParams: { returnUrl: this.getProfileReturnUrl() },
        });
    }

    rereadBook(item: ProfileReadingBook) {
        this.router.navigate(['/read', item.book.book_id, 1], {
            queryParams: { returnUrl: this.getProfileReturnUrl() },
        });
    }

    readReviewBook(item: ProfileReview) {
        const chapterId =
            item.progress !== null && item.progress < 100
                ? (item.chapter_id ?? 1)
                : 1;

        this.router.navigate(['/read', item.book.book_id, chapterId], {
            queryParams: { returnUrl: this.getProfileReturnUrl() },
        });
    }

    getReviewBookAction(item: ProfileReview): string {
        if (item.progress === null) return 'Читать';
        return item.progress >= 100 ? 'Перечитать' : 'Продолжить';
    }

    openBookDetails(bookId: number) {
        this.isDetailsLoading.set(true);
        this.bookDataService
            .getBookById(bookId)
            .pipe(finalize(() => this.isDetailsLoading.set(false)))
            .subscribe({
                next: (book) => this.selectedBook.set(book),
                error: (err) => {
                    console.error(err);
                    this.error.set('Не удалось загрузить данные книги');
                },
            });
    }

    closeDetails() {
        this.selectedBook.set(null);
    }

    onBookUpdated(updated: Book) {
        this.selectedBook.set(updated);
        this.loadedTabs.delete('reviews');

        this.reading.update((items) =>
            items.map((item) =>
                item.book.book_id === updated.book_id
                    ? {
                          ...item,
                          book: {
                              ...item.book,
                              avg_rating: updated.avg_rating,
                              reviews_count: updated.reviews_count,
                          },
                      }
                    : item,
            ),
        );
        this.finished.update((items) =>
            items.map((item) =>
                item.book.book_id === updated.book_id
                    ? {
                          ...item,
                          book: {
                              ...item.book,
                              avg_rating: updated.avg_rating,
                              reviews_count: updated.reviews_count,
                          },
                      }
                    : item,
            ),
        );
        this.reviews.update((items) =>
            items.map((item) =>
                item.book.book_id === updated.book_id
                    ? { ...item, book: updated }
                    : item,
            ),
        );

        if (this.activeTab() === 'reviews') {
            this.loadTab('reviews');
        }
    }

    profileReviewToReview(item: ProfileReview): Review {
        return {
            id: item.id,
            user_login: this.user()?.login ?? '',
            rating: item.rating,
            text: item.text,
            created_at: item.created_at,
            updated_at: item.updated_at,
        };
    }

    editReview(reviewId: number) {
        this.editingReviewId.set(reviewId);
    }

    cancelReviewEdit() {
        this.editingReviewId.set(null);
    }

    onReviewSaved() {
        this.editingReviewId.set(null);
        this.loadTab('reviews');
    }

    deleteReview(reviewId: number) {
        if (!confirm('Удалить ваш отзыв?')) return;

        this.reviewService.deleteReview(reviewId).subscribe({
            next: () => this.loadTab('reviews'),
            error: (err) => {
                console.error(err);
                this.error.set('Не удалось удалить отзыв');
            },
        });
    }
}
