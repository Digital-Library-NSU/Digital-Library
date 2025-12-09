import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { Book } from '../../../../shared/models/book.model';

@Component({
    selector: 'app-book-details-modal',
    imports: [CommonModule],
    templateUrl: './book-details-modal.component.html',
    styleUrl: './book-details-modal.component.scss',
})
export class BookDetailsModalComponent {
    @Input({ required: true }) book: Book | null = null;
    @Output() close = new EventEmitter<void>();

    closeModal() {
        this.close.emit();
    }
}
