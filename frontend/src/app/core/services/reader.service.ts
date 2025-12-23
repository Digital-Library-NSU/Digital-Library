import { inject, Injectable } from '@angular/core';
import { ApiService } from './api.service';
import { Observable } from 'rxjs';
import {
    ChaptersList,
    InBookSearchResponse,
} from '../../shared/models/reader.model';

@Injectable({
    providedIn: 'root',
})
export class ReaderService {
    private api = inject(ApiService);

    getAllChapters(bookId: number): Observable<ChaptersList> {
        return this.api.get<ChaptersList>(`/reader/${bookId}/chapters`);
    }

    getChapterContent(bookId: number, chapterId: number): Observable<string> {
        return this.api.get(`/reader/${bookId}/${chapterId}`, {}, 'text');
    }

    searchInBook(bookId: number, q: string): Observable<InBookSearchResponse> {
        return this.api.get<InBookSearchResponse>(`/reader/${bookId}/search`, {
            q,
        });
    }
}
