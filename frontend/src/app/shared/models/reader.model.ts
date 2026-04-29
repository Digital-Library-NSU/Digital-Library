export type Chapter = {
    chapter_id: number;
    title: string;
};

export type ChaptersList = {
    chapters: Chapter[];
};

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

export interface InBookSearchHit {
    score: number;
    snippet: Snippet;
}

export interface InBookSearchResponse {
    total: number;
    hits: InBookSearchHit[];
}
