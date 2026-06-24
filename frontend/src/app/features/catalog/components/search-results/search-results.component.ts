import { CommonModule } from '@angular/common';
import {
    Component,
    EventEmitter,
    Input,
    OnChanges,
    Output,
    SimpleChanges,
} from '@angular/core';
import { BookCardComponent } from '../book-card/book-card.component';
import { SearchHit } from '../../../../shared/models/book.model';

@Component({
    selector: 'app-search-results',
    imports: [CommonModule, BookCardComponent],
    templateUrl: './search-results.component.html',
    styleUrl: './search-results.component.scss',
})
export class SearchResultsComponent implements OnChanges {
    @Input() hits: SearchHit[] = [];
    @Input() total: number = 0;
    @Output() detailsClick = new EventEmitter<number>();

    metaHits: SearchHit[] = [];
    quoteHits: SearchHit[] = [];

    ngOnChanges(changes: SimpleChanges): void {
        if (changes['hits'] && this.hits) {
            this.splitHits();
        }
    }

    private splitHits() {
        this.metaHits = this.hits.filter((h) => h.match_type === 'meta');
        this.quoteHits = this.hits.filter(
            (h) => h.match_type === 'quote' || h.match_type === undefined
        );
    }

    onDetails(id: number) {
        this.detailsClick.emit(id);
    }
}
