import { CommonModule } from '@angular/common';
import { Component, EventEmitter, inject, Input, Output } from '@angular/core';
import { BookCard } from '../../../../shared/models/book.model';
import { environment } from '../../../../../environments/environment';
import { Router } from '@angular/router';

@Component({
    selector: 'app-book-card',
    imports: [CommonModule],
    templateUrl: './book-card.component.html',
    styleUrl: './book-card.component.scss',
})
export class BookCardComponent {
    @Input({ required: true }) book!: BookCard;
    @Output() details = new EventEmitter<number>();
    protected readonly apiUrl = environment.apiUrl;
    private router = inject(Router);

    onDetailsClick(event: Event) {
        event.stopPropagation();
        this.details.emit(this.book.book_id);
    }

    onReadClick(event: Event) {
        event.stopPropagation();
        this.router.navigate(['/read', this.book.book_id, 1]);
    }
}
