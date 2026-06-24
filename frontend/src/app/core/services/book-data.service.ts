import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import { Book, BookCard, SearchResponse } from '../../shared/models/book.model';
import { environment } from '../../../environments/environment';
import { HttpClient } from '@angular/common/http';

export type BooksSortMode = 'popular' | 'new' | 'recommended';

export interface UploadBookResponse {
    task_id: string;
    status: string;
    filename?: string | null;
}

export interface ImportTaskStatus {
    task_id: string;
    state: string;
    filename?: string | null;
    title?: string | null;
    authors?: string | null;
    stage?: string | null;
    status_label?: string | null;
    progress_percent?: number | null;
    current?: number | null;
    total?: number | null;
    unit?: string | null;
    eta_seconds?: number | null;
    queued: boolean;
    started_at?: string | null;
    updated_at?: string | null;
    result?: any;
    error?: string | null;
}

export interface CancelImportResponse {
    task_id: string;
    state: string;
    stage: string;
    status_label: string;
    filename?: string | null;
}

@Injectable({
    providedIn: 'root',
})
export class BookDataService {
    private api = inject(ApiService);
    private http = inject(HttpClient);
    private baseUrl = environment.apiUrl;

    getAllBooks(
        limit: number = 10,
        offset: number = 0,
        sort: BooksSortMode = 'popular',
    ): Observable<BookCard[]> {
        return this.api.get<BookCard[]>('/books/all', { limit, offset, sort });
    }

    getBookById(id: number): Observable<Book> {
        return this.api.get<Book>(`/books/${id}`);
    }

    deleteBook(id: number): Observable<void> {
        return this.api.delete<void>(`/books/${id}`);
    }

    uploadBook(file: File): Observable<UploadBookResponse> {
        const formData = new FormData();
        formData.append('file', file);

        return this.http.post<UploadBookResponse>(
            `${this.baseUrl}/books/upload`,
            formData,
        );
    }

    getImportStatus(taskId: string): Observable<ImportTaskStatus> {
        return this.api.get<ImportTaskStatus>(`/books/imports/${taskId}`);
    }

    getImportEventsUrl(taskIds: string[]): string {
        const ids = taskIds.map((taskId) => taskId.trim()).filter(Boolean).join(',');
        return `${this.baseUrl}/books/imports/events?ids=${encodeURIComponent(ids)}`;
    }

    cancelImport(taskId: string): Observable<CancelImportResponse> {
        return this.api.delete<CancelImportResponse>(`/books/imports/${taskId}`);
    }

    searchFullText(
        q: string,
        size: number = 12,
        offset: number = 0
    ): Observable<SearchResponse> {
        return this.api.get<SearchResponse>('/search/fulltext', {
            q,
            size,
            offset,
        });
    }

    searchSemantic(
        q: string,
        size: number = 12,
        offset: number = 0
    ): Observable<SearchResponse> {
        return this.api.get<SearchResponse>('/search/semantic', {
            q,
            size,
            offset,
        });
    }
}
