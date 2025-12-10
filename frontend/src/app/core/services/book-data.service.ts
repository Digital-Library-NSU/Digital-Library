import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import { Book, BookCard } from '../../shared/models/book.model';
import { environment } from '../../../environments/environment';
import { HttpClient } from '@angular/common/http';

@Injectable({
    providedIn: 'root',
})
export class BookDataService {
    private api = inject(ApiService);
    private http = inject(HttpClient);
    private baseUrl = environment.apiUrl;

    getAllBooks(
        limit: number = 10,
        offset: number = 0
    ): Observable<BookCard[]> {
        return this.api.get<BookCard[]>('/books/all', { limit, offset });
    }

    getBookById(id: number): Observable<Book> {
        return this.api.get<Book>(`/books/${id}`);
    }

    uploadBook(file: File): Observable<any> {
        const formData = new FormData();
        formData.append('file', file);

        return this.http.post(`${this.baseUrl}/books/upload`, formData);
    }
}
