import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { Book } from '../../../../shared/models/book.model';
import { environment } from '../../../../../environments/environment';

@Component({
    selector: 'app-book-details-modal',
    imports: [CommonModule],
    templateUrl: './book-details-modal.component.html',
    styleUrl: './book-details-modal.component.scss',
})
export class BookDetailsModalComponent {
    @Input({ required: true }) book: Book | null = null;
    @Output() close = new EventEmitter<void>();

    protected readonly apiUrl = environment.apiUrl;

    closeModal() {
        this.close.emit();
    }
}
