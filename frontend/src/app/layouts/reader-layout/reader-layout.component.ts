import { Component } from '@angular/core';
import { ReaderComponent } from '../../features/reader/reader.component';

@Component({
    selector: 'app-reader-layout',
    imports: [ReaderComponent],
    templateUrl: './reader-layout.component.html',
    styleUrl: './reader-layout.component.scss',
})
export class ReaderLayoutComponent {}
