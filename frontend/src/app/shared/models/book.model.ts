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
