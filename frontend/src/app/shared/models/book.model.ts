export interface BookCard {
    book_id: number;
    title: string;
    cover_path: string | null;
    authors: string;
    avg_rating: number | null;
    reviews_count: number;
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
    avg_rating: number | null;
    reviews_count: number;
}

export interface Snippet {
    doc_id: string;
    chapter_id: number | null;
    chapter_ord: number;
    chapter_path: string;
    chapter_title: string | null;
    snippet: string;
    block_start?: number | null;
    block_end?: number | null;
    hit_block_index?: number | null;
}

export interface SearchHit {
    book: BookCard;
    score: number;
    match_type?: 'meta' | 'quote';
    snippet: Snippet | null;
}

export interface SearchResponse {
    total: number;
    hits: SearchHit[];
}
