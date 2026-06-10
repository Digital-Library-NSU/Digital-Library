import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';
import { getFieldErrorMessage } from '../../../shared/utils/form-error-message';

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
    submitted = false;
    errorMessage = '';

    form = this.fb.nonNullable.group({
        login: ['', [Validators.required, Validators.maxLength(255)]],
        password: ['', [Validators.required]],
    });

    errorFor(controlName: string): string | null {
        const control = this.form.get(controlName);
        if (!control || !control.invalid) return null;
        if (!control.touched && !this.submitted) return null;

        return getFieldErrorMessage(control.errors);
    }

    submit() {
        this.submitted = true;

        if (this.form.invalid || this.isSubmitting) return;

        this.isSubmitting = true;
        this.errorMessage = '';
        this.form.disable();

        this.auth.login(this.form.getRawValue()).subscribe({
            next: () => {
                this.isSubmitting = false;
                this.form.enable();
                this.submitted = false;
                const returnUrl =
                    this.route.snapshot.queryParamMap.get('returnUrl') || '/';
                this.router.navigateByUrl(returnUrl);
            },
            error: (err: HttpErrorResponse) => {
                this.isSubmitting = false;
                this.form.enable();
                this.submitted = false;
                this.errorMessage =
                    err.error?.detail ||
                    'Не удалось войти. Проверьте логин и пароль.';
            },
        });
    }
}
