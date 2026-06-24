import { computed, inject, Injectable, signal } from '@angular/core';
import { catchError, Observable, of, switchMap, tap } from 'rxjs';
import { ApiService } from './api.service';
import { AuthDTO, UserInfo } from '../../shared/models/auth.model';

@Injectable({
    providedIn: 'root',
})
export class AuthService {
    private api = inject(ApiService);

    readonly user = signal<UserInfo | null>(null);
    readonly isAuthenticated = computed(() => this.user() !== null);
    readonly isAdmin = computed(() => this.user()?.role === 'admin');

    loadCurrentUser(): Observable<UserInfo | null> {
        return this.api.get<UserInfo>('/user/info').pipe(
            tap((info) => this.user.set(info)),
            catchError(() => {
                this.user.set(null);
                return of(null);
            }),
        );
    }

    register(dto: AuthDTO): Observable<UserInfo | null> {
        return this.api
            .post<void>('/auth/register', dto)
            .pipe(switchMap(() => this.loadCurrentUser()));
    }

    login(dto: AuthDTO): Observable<UserInfo | null> {
        return this.api
            .post<void>('/auth/login', dto)
            .pipe(switchMap(() => this.loadCurrentUser()));
    }

    logout(): Observable<void> {
        return this.api
            .post<void>('/auth/logout', {})
            .pipe(tap(() => this.user.set(null)));
    }

    clearUser(): void {
        this.user.set(null);
    }
}
