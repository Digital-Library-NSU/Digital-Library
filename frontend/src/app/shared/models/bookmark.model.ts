export interface Bookmark {
    bookmark_id: number;
    chapter_id: number;       // используется в reader и bookmarks-panel
    data_block_index: number; // используется для scrollToBlock и сортировки
    page?: number;
    text?: string;
    note?: string;
    created_at?: string;
    updated_at?: string;
}

// Интерфейс запроса на создание закладки
export interface CreateBookmarkRequest {
    chapter_id: number;
    page?: number;
    text?: string;
    note?: string;
    data_block_index?: number; // нужно для сервисов
}
