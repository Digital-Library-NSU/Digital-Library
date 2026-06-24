import { CommonModule } from '@angular/common';
import {
    Component,
    effect,
    inject,
    input,
    output,
    signal,
} from '@angular/core';
import { forkJoin } from 'rxjs';
import { AuthService } from '../../../../core/services/auth.service';
import { ReviewService } from '../../../../core/services/review.service';
import { Review } from '../../../../shared/models/review.model';
import { ReviewFormComponent } from './components/review-form/review-form.component';
import { ReviewItemComponent } from './components/review-item/review-item.component';

@Component({
    selector: 'app-book-reviews',
    imports: [CommonModule, ReviewFormComponent, ReviewItemComponent],
    templateUrl: './book-reviews.component.html',
    styleUrl: './book-reviews.component.scss',
})
export class BookReviewsComponent {
    bookId = input.required<number>();

    reviewsChanged = output<void>();

    private auth = inject(AuthService);
    private reviewService = inject(ReviewService);

    readonly isAuthenticated = this.auth.isAuthenticated;

    readonly reviews = signal<Review[]>([]);
    readonly myReview = signal<Review | null>(null);
    readonly isLoading = signal<boolean>(false);
    readonly isEditing = signal<boolean>(false);

    constructor() {
        effect(() => {
            const id = this.bookId();
            this.loadReviews(id);
        });
    }

    private loadReviews(bookId: number) {
        this.isLoading.set(true);

        if (!this.isAuthenticated()) {
            this.reviewService.getBookReviews(bookId).subscribe({
                next: (list) => {
                    this.reviews.set(list);
                    this.myReview.set(null);
                    this.isLoading.set(false);
                },
                error: () => this.isLoading.set(false),
            });
            return;
        }

        forkJoin({
            list: this.reviewService.getBookReviews(bookId),
            mine: this.reviewService.getMyReview(bookId),
        }).subscribe({
            next: ({ list, mine }) => {
                this.myReview.set(mine);

                const filtered = mine
                    ? list.filter((r) => r.id !== mine.id)
                    : list;

                this.reviews.set(filtered);
                this.isLoading.set(false);
            },
            error: () => this.isLoading.set(false),
        });
    }

    onFormSaved() {
        this.isEditing.set(false);
        this.loadReviews(this.bookId());
        this.reviewsChanged.emit();
    }

    onFormCancelled() {
        this.isEditing.set(false);
    }

    onEditMyReview() {
        this.isEditing.set(true);
    }

    onDeleteMyReview(reviewId: number) {
        if (!confirm('Удалить ваш отзыв?')) return;

        this.reviewService.deleteReview(reviewId).subscribe({
            next: () => {
                this.loadReviews(this.bookId());
                this.reviewsChanged.emit();
            },
        });
    }
}
