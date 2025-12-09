import { Component } from '@angular/core';
import { HeaderComponent } from '../header/header/header.component';
import { CatalogComponent } from '../../features/catalog/catalog.component';

@Component({
    selector: 'app-main-layout',
    imports: [HeaderComponent, CatalogComponent],
    templateUrl: './main-layout.component.html',
    styleUrl: './main-layout.component.scss',
})
export class MainLayoutComponent {}
