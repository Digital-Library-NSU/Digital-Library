import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { BookCardComponent } from '../book-card/book-card.component';
import { SearchHit } from '../../../../shared/models/book.model';

@Component({
    selector: 'app-search-results',
    imports: [CommonModule, BookCardComponent],
    templateUrl: './search-results.component.html',
    styleUrl: './search-results.component.scss',
})
export class SearchResultsComponent {
    @Input() hits: SearchHit[] = [];
    @Input() total: number = 0;
    @Output() detailsClick = new EventEmitter<number>();

    onDetails(id: number) {
        this.detailsClick.emit(id);
    }
}
