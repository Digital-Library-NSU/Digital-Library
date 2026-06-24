import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import {
    ProfileReadingBook,
    ProfileReview,
} from '../../shared/models/profile.model';

@Injectable({
    providedIn: 'root',
})
export class ProfileService {
    private api = inject(ApiService);

    getReading(): Observable<ProfileReadingBook[]> {
        return this.api.get<ProfileReadingBook[]>('/user/profile/reading');
    }

    getFinished(): Observable<ProfileReadingBook[]> {
        return this.api.get<ProfileReadingBook[]>('/user/profile/finished');
    }

    getReviews(): Observable<ProfileReview[]> {
        return this.api.get<ProfileReview[]>('/user/profile/reviews');
    }
}
