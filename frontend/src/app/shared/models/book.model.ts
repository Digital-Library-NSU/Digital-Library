export interface BookCard {
    book_id: number;
    title: string;
    cover_path: string | null;
    authors: string;
}

export interface Book {
    book_id: number;
    title: string;
    lang: string | null;
    description: string | null;
    publisher: string | null;
    pub_date: string | null;
    subjects: string | null;
    series: string | null;
    cover_path: string | null;
    authors: string;
}

export interface Snippet {
    doc_id: string;
    edition_id: string;
    chapter_ord: number;
    chapter_path: string;
    chapter_title: string | null;
    snippet: string;
}

export interface SearchHit {
    book: BookCard;
    score: number;
    match_type: 'meta' | 'quote';
    snippet: Snippet | null;
}

export interface SearchResponse {
    total: number;
    hits: SearchHit[];
}
