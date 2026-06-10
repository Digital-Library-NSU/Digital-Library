import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';
import { AuthService } from '../services/auth.service';

const SKIP_REDIRECT = [
    '/auth/login',
    '/auth/register',
    '/user/info',
    '/bookmarks',
];

export const authErrorInterceptor: HttpInterceptorFn = (req, next) => {
    const auth = inject(AuthService);
    const router = inject(Router);

    return next(req).pipe(
        catchError((err: HttpErrorResponse) => {
            if (err.status === 401) {
                auth.clearUser();

                const shouldRedirect = !SKIP_REDIRECT.some((p) =>
                    req.url.includes(p),
                );
                if (shouldRedirect) {
                    router.navigate(['/login']);
                }
            }
            return throwError(() => err);
        }),
    );
};
