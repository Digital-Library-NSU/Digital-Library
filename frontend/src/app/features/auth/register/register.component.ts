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

function passwordsMatch(group: AbstractControl): ValidationErrors | null {
    const pwd = group.get('password')?.value;
    const confirm = group.get('confirmPassword')?.value;
    return pwd === confirm ? null : { passwordsMismatch: true };
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
    errorMessage = '';

    form = this.fb.nonNullable.group(
        {
            login: [
                '',
                [Validators.required, Validators.maxLength(255)],
            ],
            password: [
                '',
                [Validators.required, Validators.minLength(6)],
            ],
            confirmPassword: ['', [Validators.required]],
        },
        { validators: passwordsMatch }
    );

    submit() {
        if (this.form.invalid || this.isSubmitting) return;

        const { login, password } = this.form.getRawValue();

        this.isSubmitting = true;
        this.errorMessage = '';

        this.auth.register({ login, password }).subscribe({
            next: () => {
                this.isSubmitting = false;
                this.router.navigateByUrl('/');
            },
            error: (err: HttpErrorResponse) => {
                this.isSubmitting = false;
                this.errorMessage =
                    err.error?.detail ||
                    'Не удалось зарегистрироваться. Попробуйте ещё раз.';
            },
        });
    }
}
