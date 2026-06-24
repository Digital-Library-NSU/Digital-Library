import { Book, BookCard } from './book.model';

export interface ProfileReadingBook {
    book: BookCard;
    progress: number;
    chapter_id: number;
}

export interface ProfileReview {
    id: number;
    rating: number;
    text: string;
    created_at: string;
    updated_at: string | null;
    progress: number | null;
    chapter_id: number | null;
    book: Book;
}
