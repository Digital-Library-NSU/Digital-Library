import { ComponentFixture, TestBed } from '@angular/core/testing';

import { UploadBookModalComponent } from './upload-book-modal.component';

describe('UploadBookModalComponent', () => {
  let component: UploadBookModalComponent;
  let fixture: ComponentFixture<UploadBookModalComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [UploadBookModalComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(UploadBookModalComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
