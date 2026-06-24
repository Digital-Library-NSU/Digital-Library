import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject } from '@angular/core';
import {
    AbstractControl,
    FormBuilder,
    ReactiveFormsModule,
    ValidationErrors,
    Validators,
} from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';
import { getFieldErrorMessage } from '../../../shared/utils/form-error-message';

function passwordsMatch(group: AbstractControl): ValidationErrors | null {
    const pwd = group.get('password')?.value;
    const confirm = group.get('confirmPassword')?.value;
    return pwd === confirm ? null : { passwordsMismatch: true };
}

function emailRequiredForNotifications(group: AbstractControl): ValidationErrors | null {
    const notify = group.get('notify_recommendations')?.value;
    const email = group.get('email')?.value;

    return notify && !email ? { emailRequiredForNotifications: true } : null;
}

@Component({
    selector: 'app-register',
    imports: [CommonModule, ReactiveFormsModule, RouterLink],
    templateUrl: './register.component.html',
    styleUrl: './register.component.scss',
})
export class RegisterComponent {
    private fb = inject(FormBuilder);
    private auth = inject(AuthService);
    private router = inject(Router);

    isSubmitting = false;
    submitted = false;
    errorMessage = '';

    form = this.fb.nonNullable.group(
        {
            login: ['', [Validators.required, Validators.maxLength(255)]],
            email: ['', [Validators.email, Validators.maxLength(320)]],
            notify_recommendations: [false],
            password: ['', [Validators.required, Validators.minLength(6)]],
            confirmPassword: ['', [Validators.required]],
        },
        { validators: [passwordsMatch, emailRequiredForNotifications] },
    );

    errorFor(controlName: string): string | null {
        const control = this.form.get(controlName);
        if (!control || !control.invalid) return null;
        if (!control.touched && !this.submitted) return null;

        return getFieldErrorMessage(control.errors);
    }

    showPasswordsMismatch(): boolean {
        const confirm = this.form.get('confirmPassword');

        return (
            !!this.form.errors?.['passwordsMismatch'] &&
            !!confirm?.valid &&
            (confirm.touched || this.submitted)
        );
    }

    showEmailRequiredForNotifications(): boolean {
        const email = this.form.get('email');

        return (
            !!this.form.errors?.['emailRequiredForNotifications'] &&
            (email?.touched || this.submitted)
        );
    }

    submit() {
        this.submitted = true;

        if (this.form.invalid || this.isSubmitting) return;

        const { login, password, email, notify_recommendations } = this.form.getRawValue();

        this.isSubmitting = true;
        this.errorMessage = '';
        this.form.disable();

        this.auth.register({
            login,
            password,
            email: email || null,
            notify_recommendations,
        }).subscribe({
            next: () => {
                this.isSubmitting = false;
                this.form.enable();
                this.submitted = false;
                this.router.navigateByUrl('/');
            },
            error: (err: HttpErrorResponse) => {
                this.errorMessage =
                    err.error?.detail ||
                    'Не удалось зарегистрироваться. Попробуйте ещё раз.';
                this.isSubmitting = false;
                this.form.enable();
                this.submitted = false;
            },
        });
    }
}
