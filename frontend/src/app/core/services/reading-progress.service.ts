import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';

export interface ReadingProgress {
    book_id: number;
    chapter_id: number;
    data_block_index: number;
    block_char_offset: number;
    chapter_scroll_ratio: number;
    progress: number;
}

export interface SetReadingProgressRequest {
    book_id: number;
    chapter_id: number;
    data_block_index: number;
    block_char_offset: number;
    chapter_scroll_ratio: number;
    is_completed?: boolean;
}

@Injectable({
    providedIn: 'root',
})
export class ReadingProgressService {
    private api = inject(ApiService);

    getAll(): Observable<ReadingProgress[]> {
        return this.api.get<ReadingProgress[]>('/read-prog/');
    }

    set(body: SetReadingProgressRequest): Observable<ReadingProgress> {
        return this.api.post<ReadingProgress>('/read-prog/', body);
    }
}
