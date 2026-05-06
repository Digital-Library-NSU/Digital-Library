import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject } from '@angular/core';
import {
    FormBuilder,
    ReactiveFormsModule,
    Validators,
} from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';

@Component({
    selector: 'app-login',
    imports: [CommonModule, ReactiveFormsModule, RouterLink],
    templateUrl: './login.component.html',
    styleUrl: './login.component.scss',
})
export class LoginComponent {
    private fb = inject(FormBuilder);
    private auth = inject(AuthService);
    private router = inject(Router);
    private route = inject(ActivatedRoute);

    isSubmitting = false;
    errorMessage = '';

    form = this.fb.nonNullable.group({
        login: [
            '',
            [Validators.required, Validators.maxLength(255)],
        ],
        password: ['', [Validators.required]],
    });

    submit() {
        if (this.form.invalid || this.isSubmitting) return;

        this.isSubmitting = true;
        this.errorMessage = '';

        this.auth.login(this.form.getRawValue()).subscribe({
            next: () => {
                this.isSubmitting = false;
                const returnUrl =
                    this.route.snapshot.queryParamMap.get('returnUrl') || '/';
                this.router.navigateByUrl(returnUrl);
            },
            error: (err: HttpErrorResponse) => {
                this.isSubmitting = false;
                this.errorMessage =
                    err.error?.detail ||
                    'Не удалось войти. Проверьте логин и пароль.';
            },
        });
    }
}
