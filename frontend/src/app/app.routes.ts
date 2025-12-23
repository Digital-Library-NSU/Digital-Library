import { Routes } from '@angular/router';
import { MainLayoutComponent } from './layouts/main-layout/main-layout.component';
import { ReaderLayoutComponent } from './layouts/reader-layout/reader-layout.component';

export const routes: Routes = [
    { path: '', component: MainLayoutComponent },
    { path: 'read/:id/:chapterId', component: ReaderLayoutComponent },
];
