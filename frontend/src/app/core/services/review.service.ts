import { Injectable, inject } from '@angular/core';
import { Observable, catchError, of } from 'rxjs';
import { HttpErrorResponse } from '@angular/common/http';
import { ApiService } from './api.service';
import {
    CreateReviewRequest,
    Review,
} from '../../shared/models/review.model';

@Injectable({
    providedIn: 'root',
})
export class ReviewService {
    private api = inject(ApiService);

    getBookReviews(bookId: number): Observable<Review[]> {
        return this.api.get<Review[]>(`/books/${bookId}/reviews`);
    }

    getMyReview(bookId: number): Observable<Review | null> {
        return this.api.get<Review>(`/books/${bookId}/my-review`).pipe(
            catchError((err: HttpErrorResponse) => {
                if (err.status === 404) return of(null);
                throw err;
            }),
        );
    }

    upsertReview(
        bookId: number,
        body: CreateReviewRequest,
    ): Observable<{ ok: true }> {
        return this.api.post<{ ok: true }>(`/books/${bookId}/review`, body);
    }

    deleteReview(reviewId: number): Observable<{ ok: true }> {
        return this.api.delete<{ ok: true }>(`/books/reviews/${reviewId}`);
    }
}
