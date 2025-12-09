import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { BookCard } from '../../../../shared/models/book.model';

@Component({
    selector: 'app-book-card',
    imports: [CommonModule],
    templateUrl: './book-card.component.html',
    styleUrl: './book-card.component.scss',
})
export class BookCardComponent {
    @Input({ required: true }) book!: BookCard;
    @Output() details = new EventEmitter<number>();

    onDetailsClick(event: Event) {
        event.stopPropagation();
        this.details.emit(this.book.book_id);
    }
}
