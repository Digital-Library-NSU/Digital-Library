import {
    ApplicationConfig,
    inject,
    provideAppInitializer,
    provideZoneChangeDetection,
} from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

import { routes } from './app.routes';
import { withCredentialsInterceptor } from './core/interceptors/with-credentials.interceptor';
import { authErrorInterceptor } from './core/interceptors/auth-error.interceptor';
import { AuthService } from './core/services/auth.service';

export const appConfig: ApplicationConfig = {
    providers: [
        provideZoneChangeDetection({ eventCoalescing: true }),
        provideRouter(routes),
        provideHttpClient(
            withInterceptors([
                withCredentialsInterceptor,
                authErrorInterceptor,
            ])
        ),
        provideAppInitializer(() => {
            const auth = inject(AuthService);
            return firstValueFrom(auth.loadCurrentUser());
        }),
    ],
};
