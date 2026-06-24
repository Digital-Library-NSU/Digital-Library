import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

@Injectable({
    providedIn: 'root',
})
export class ApiService {
    private http = inject(HttpClient);
    private baseUrl = environment.apiUrl;

    get<T>(
        path: string,
        params: Record<string, any> = {},
        responseType: 'json' | 'text' = 'json'
    ): Observable<T> {
        let httpParams = new HttpParams();
        Object.keys(params).forEach((key) => {
            if (params[key] !== null && params[key] !== undefined) {
                httpParams = httpParams.append(key, params[key]);
            }
        });

        return this.http.get<T>(`${this.baseUrl}${path}`, {
            params: httpParams,
            responseType: responseType as any,
        });
    }

    post<T>(path: string, body: any = {}): Observable<T> {
        return this.http.post<T>(`${this.baseUrl}${path}`, body);
    }

    delete<T>(path: string): Observable<T> {
        return this.http.delete<T>(`${this.baseUrl}${path}`);
    }
}
