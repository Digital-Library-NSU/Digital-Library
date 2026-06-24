import { CommonModule } from '@angular/common';
import { Component, inject } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';

@Component({
    selector: 'app-header',
    imports: [CommonModule, RouterLink],
    templateUrl: './header.component.html',
    styleUrl: './header.component.scss',
})
export class HeaderComponent {
    private auth = inject(AuthService);
    private router = inject(Router);

    readonly user = this.auth.user;

    logout() {
        this.auth.logout().subscribe({
            next: () => this.router.navigate(['/']),
            error: () => this.router.navigate(['/']),
        });
    }

    toggleProfile() {
        this.router.navigate([
            this.router.url.startsWith('/profile') ? '/' : '/profile',
        ]);
    }
}
