import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { HeaderComponent } from './layouts/header/header/header.component';
import { MainLayoutComponent } from './layouts/main-layout/main-layout.component';

@Component({
    selector: 'app-root',
    imports: [RouterOutlet, MainLayoutComponent],
    templateUrl: './app.component.html',
    styleUrl: './app.component.scss',
})
export class AppComponent {
    title = 'library-web';
}
