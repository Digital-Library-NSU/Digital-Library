export interface Review {
    id: number;
    user_login: string;
    rating: number;
    text: string;
    created_at: string;
    updated_at: string | null;
}

export interface CreateReviewRequest {
    rating: number;
    text: string;
}
