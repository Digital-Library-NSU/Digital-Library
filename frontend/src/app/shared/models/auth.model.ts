export interface AuthDTO {
    login: string;
    password: string;
    email?: string | null;
    notify_recommendations?: boolean;
}

export interface UserInfo {
    login: string;
    role: string;
}
