import { ValidationErrors } from '@angular/forms';

export function getFieldErrorMessage(
    errors: ValidationErrors | null,
): string | null {
    if (!errors) return null;

    if (errors['required']) return 'Поле обязательно для заполнения.';
    if (errors['minlength']) {
        return `Минимум ${errors['minlength'].requiredLength} символов.`;
    }
    if (errors['maxlength']) {
        return `Максимум ${errors['maxlength'].requiredLength} символов.`;
    }

    return 'Некорректное значение.';
}
