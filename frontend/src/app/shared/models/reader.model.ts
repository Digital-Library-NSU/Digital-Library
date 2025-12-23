export type Chapter = {
    chapter_id: number;
    title: string;
};

export type ChaptersList = {
    chapters: Chapter[];
};

export interface Snippet {
    doc_id: string;
    edition_id: string;
    chapter_ord: number;
    chapter_path: string;
    chapter_title: string | null;
    snippet: string;
    paragraph_id?: number;
    para_start?: number;
    para_end?: number;
    para_index_in_chapter?: number;
}

export interface InBookSearchHit {
    score: number;
    snippet: Snippet;
}

export interface InBookSearchResponse {
    total: number;
    hits: InBookSearchHit[];
}
