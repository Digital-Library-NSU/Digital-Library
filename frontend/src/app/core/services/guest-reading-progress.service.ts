import { Injectable } from '@angular/core';

export interface GuestReadingProgress {
    bookId: number;
    chapterId: number;
    dataBlockIndex: number;
    scrollLeft?: number;
}

@Injectable({
    providedIn: 'root',
})
export class GuestReadingProgressService {
    private readonly keyPrefix = 'reader-progress';

    get(bookId: number): GuestReadingProgress | null {
        const raw = sessionStorage.getItem(this.getKey(bookId));
        if (!raw) return null;

        try {
            const parsed = JSON.parse(raw) as GuestReadingProgress;

            if (
                parsed.bookId !== bookId ||
                !Number.isFinite(parsed.chapterId) ||
                !Number.isFinite(parsed.dataBlockIndex) ||
                (
                    parsed.scrollLeft !== undefined &&
                    !Number.isFinite(parsed.scrollLeft)
                )
            ) {
                return null;
            }

            return parsed;
        } catch {
            return null;
        }
    }

    set(progress: GuestReadingProgress): void {
        sessionStorage.setItem(
            this.getKey(progress.bookId),
            JSON.stringify(progress),
        );
    }

    clear(bookId: number): void {
        sessionStorage.removeItem(this.getKey(bookId));
    }

    private getKey(bookId: number): string {
        return `${this.keyPrefix}:${bookId}`;
    }
}
