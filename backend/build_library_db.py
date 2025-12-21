import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional

import requests
from tqdm import tqdm

from app.import_epub.schema import ensure_database, connect, drop_schema, apply_schema
from app.import_epub.es_support import ensure_es_indices
from app.import_epub.importer import process_epub


def main():
    ap = argparse.ArgumentParser(
        description="EPUB -> Postgres (meta) + Elasticsearch (paragraphs + embeddings)."
    )
    ap.add_argument(
        "--dsn",
        default="postgresql://libuser:libpass@localhost:5432/library",
        help="PostgreSQL DSN",
    )
    ap.add_argument(
        "--root",
        required=True,
        help="Папка с файлами .epub  или одиночный .epub-файл",
    )
    ap.add_argument("--create-db", action="store_true")
    ap.add_argument("--recreate-schema", action="store_true")

    # ES
    ap.add_argument("--no-es", action="store_true")
    ap.add_argument("--es-url", type=str, default="http://localhost:9200")
    ap.add_argument("--es-index-meta", type=str, default="books_meta")
    ap.add_argument("--es-index-content", type=str, default="books_content")
    ap.add_argument(
        "--recreate-es",
        action="store_true",
        help="Полностью удалить индексы ES (--es-index-meta и --es-index-content) перед созданием",
    )
    ap.add_argument("--es-no-source", action="store_true", help="Отключить хранение _source в индексе контента")
    ap.add_argument("--es-use-templates", action="store_true", help="Создавать index templates для индексов книг")
    ap.add_argument(
        "--es-dense-vector-dim",
        type=int,
        default=1024,
        help="Размер поля content_vec.",
    )
    ap.add_argument("--es-enable-suggest", action="store_true")

    # абзацы/окна
    ap.add_argument("--min-paragraph-words", type=int, default=15)
    ap.add_argument(
        "--no-join-short-paragraphs",
        action="store_true",
        help="Не склеивать короткие абзацы (по умолчанию склеиваем)",
    )
    ap.add_argument("--para-window-size", type=int, default=2, help=">=1 (1 = без перекрытий)")
    ap.add_argument("--para-window-stride", type=int, default=1, help=">=1 (1 = максимальное перекрытие)")

    # битые EPUB
    ap.add_argument(
        "--max-missing-spine",
        type=int,
        default=50,
        help="Сколько отсутствующих ресурсов в spine допускаем, прежде чем пропустить EPUB",
    )
    ap.add_argument(
        "--warn-cap",
        type=int,
        default=5,
        help="Сколько первых предупреждений про отсутствующие ресурсы печатать",
    )

    # эмбеддинги
    ap.add_argument(
        "--embed-model",
        type=str,
        default="./models/bge-m3",
        help="Путь к модели или HF id (например, BAAI/bge-m3). Пусто — без эмбеддингов.",
    )
    ap.add_argument("--embed-device", type=str, default="auto", help="auto|cpu|cuda|mps")
    ap.add_argument("--embed-batch-size", type=int, default=64)
    ap.add_argument(
        "--embed-max-words",
        type=int,
        default=256,
        help="Макс. слов в одном векторе; больше — дробим на под-чанки",
    )
    ap.add_argument(
        "--embed-overlap-words",
        type=int,
        default=32,
        help="Перекрытие между под-чанками при дроблении",
    )
    ap.add_argument(
        "--no-embed-normalize",
        action="store_true",
        help="Не нормализовать эмбеддинги (по умолчанию нормализуем)",
    )

    ap.add_argument("--limit", type=int, default=0)

    # экспорт обложек и глав
    ap.add_argument(
        "--export-root",
        type=str,
        default="./books_content",
        help="Директория, куда складывать обложки и главы книг (по book_id).",
    )

    ap.add_argument(
        "--workers",
        type=int,
        default= 1,
        help="Количество параллельных воркеров (processes). 1 = без параллелизма.",
    )

    args = ap.parse_args()

    if args.create_db:
        ensure_database(args.dsn)

    conn = connect(args.dsn)
    try:
        if args.recreate_schema:
            drop_schema(conn)
        apply_schema(conn)
    except Exception:
        pass
    finally:
        conn.close()

    skipped_epubs: List[str] = []
    failed_epubs: List[str] = []

    export_root: Optional[Path] = None
    if args.export_root:
        export_root = Path(args.export_root).expanduser()
        export_root.mkdir(parents=True, exist_ok=True)


    if not args.no_es:
        if args.recreate_es:
            for name in (args.es_index_meta, args.es_index_content):
                try:
                    r = requests.delete(f"{args.es_url}/{name}", timeout=30)
                    if r.status_code not in (200, 202, 404):
                        print(f"[WARN] ES delete {name}: {r.status_code} {r.text[:200]}", file=sys.stderr)
                except Exception as e:
                    print(f"[WARN] ES delete {name} failed: {e}", file=sys.stderr)

        ensure_es_indices(
            args.es_url,
            args.es_index_meta,
            args.es_index_content,
            store_source=not args.es_no_source,
            use_templates=args.es_use_templates,
            dense_vec_dim=max(0, args.es_dense_vector_dim),
            enable_suggest=args.es_enable_suggest,
        )


    root = Path(args.root).expanduser()
    if root.is_file():
        if root.suffix.lower() != ".epub":
            print(f"[ERROR] Формат файла не EPUB: {root}", file=sys.stderr)
            return
        files = [root]
    else:
        files = sorted(p for p in root.rglob("*.epub"))

    if args.limit > 0:
        files = files[: args.limit]

    if not files:
        print("[INFO] EPUB файлы не найдены по указанному пути.", file=sys.stderr)
        return


    if args.workers <= 1:
        for p in tqdm(files, desc="Importing EPUBs"):
            try:
                status = process_epub(p, args)
                if status == "skipped":
                    skipped_epubs.append(p.name)
            except Exception as e:
                failed_epubs.append(p.name)
                print(f"[ERROR] {p.name}: {e}", file=sys.stderr)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            future_to_path = {ex.submit(process_epub, p, args): p for p in files}

            for fut in tqdm(
                as_completed(future_to_path),
                total=len(future_to_path),
                desc="Importing EPUBs",
            ):
                p = future_to_path[fut]
                try:
                    status = fut.result()
                    if status == "skipped":
                        skipped_epubs.append(p.name)
                except Exception as e:
                    failed_epubs.append(p.name)
                    print(f"[ERROR] {p.name}: {e}", file=sys.stderr)


    if skipped_epubs:
        print("\n[INFO] Skipped EPUBs due to excessive missing spine resources:")
        for name in skipped_epubs:
            print(f"  - {name}")
    else:
        print("\n[INFO] No EPUBs were skipped.")

    if failed_epubs:
        print("\n[INFO] Failed EPUBs due to errors:")
        for name in failed_epubs:
            print(f"  - {name}")


if __name__ == "__main__":
    main()
