import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import { Book, BookCard } from '../../shared/models/book.model';

@Injectable({
    providedIn: 'root',
})
export class BookDataService {
    private api = inject(ApiService);

    getAllBooks(
        limit: number = 10,
        offset: number = 0
    ): Observable<BookCard[]> {
        return this.api.get<BookCard[]>('/books/all', { limit, offset });
    }

    getBookById(id: number): Observable<Book> {
        return this.api.get<Book>(`/books/${id}`);
    }
}
