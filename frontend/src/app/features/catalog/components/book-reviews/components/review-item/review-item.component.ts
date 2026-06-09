import { CommonModule, DatePipe } from '@angular/common';
import { Component, input, output } from '@angular/core';
import { Review } from '../../../../../../shared/models/review.model';

@Component({
    selector: 'app-review-item',
    imports: [CommonModule, DatePipe],
    templateUrl: './review-item.component.html',
    styleUrl: './review-item.component.scss',
})
export class ReviewItemComponent {
    review = input.required<Review>();
    canDelete = input<boolean>(false);
    canEdit = input<boolean>(false);

    delete = output<number>();
    edit = output<void>();

    onDelete() {
        this.delete.emit(this.review().id);
    }

    onEdit() {
        this.edit.emit();
    }
}
