export interface Review {
    id: number;
    user_login: string;
    rating: number;
    text: string;
    created_at: string;
}

export interface CreateReviewRequest {
    rating: number;
    text: string;
}
