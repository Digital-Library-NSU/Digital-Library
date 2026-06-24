import { HttpInterceptorFn } from '@angular/common/http';

export const withCredentialsInterceptor: HttpInterceptorFn = (req, next) => {
    return next(req.clone({ withCredentials: true }));
};
