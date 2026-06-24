import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, effect, inject, input, output } from '@angular/core';
import {
    FormBuilder,
    ReactiveFormsModule,
    Validators,
} from '@angular/forms';
import { ReviewService } from '../../../../../../core/services/review.service';
import { CreateReviewRequest } from '../../../../../../shared/models/review.model';

@Component({
    selector: 'app-review-form',
    imports: [CommonModule, ReactiveFormsModule],
    templateUrl: './review-form.component.html',
    styleUrl: './review-form.component.scss',
})
export class ReviewFormComponent {
    bookId = input.required<number>();
    initialRating = input<number | null>(null);
    initialText = input<string | null>(null);
    isEditing = input<boolean>(false);

    saved = output<void>();
    cancelled = output<void>();

    private fb = inject(FormBuilder);
    private reviewService = inject(ReviewService);

    isSubmitting = false;
    errorMessage = '';

    form = this.fb.nonNullable.group({
        rating: [
            10,
            [Validators.required, Validators.min(1), Validators.max(10)],
        ],
        text: ['', [Validators.required, Validators.maxLength(5000)]],
    });

    constructor() {
        effect(() => {
            const rating = this.initialRating();
            const text = this.initialText();

            this.form.reset({
                rating: rating ?? 10,
                text: text ?? '',
            });
        });
    }

    submit() {
        if (this.form.invalid || this.isSubmitting) return;

        this.isSubmitting = true;
        this.errorMessage = '';

        const body: CreateReviewRequest = this.form.getRawValue();

        this.reviewService.upsertReview(this.bookId(), body).subscribe({
            next: () => {
                this.isSubmitting = false;
                this.saved.emit();
            },
            error: (err: HttpErrorResponse) => {
                this.isSubmitting = false;
                this.errorMessage =
                    err.error?.detail || 'Не удалось сохранить отзыв.';
            },
        });
    }

    cancel() {
        this.cancelled.emit();
    }
}
