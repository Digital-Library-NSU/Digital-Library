import json
from typing import Dict, List, Optional, Any

import requests


def es_request(method: str, url: str, json_body=None, timeout=120):
    r = requests.request(method, url, json=json_body, timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(f"ES {method} {url} failed: {r.status_code} {r.text[:500]}")
    return r.json() if r.text else {}


def ensure_es_indices(
    es_url: str,
    idx_meta: str,
    idx_content: str,
    store_source: bool = True,
    use_templates: bool = True,
    dense_vec_dim: int = 0,
    enable_suggest: bool = False,
):
    analysis = {
        "char_filter": {
            "punct_strip": {
                "type": "pattern_replace",
                "pattern": r"[\p{Punct}\p{S}]+",
                "replacement": " ",
            }
        },
        "filter": {
            "russian_stop": {"type": "stop", "stopwords": "_russian_"},
            "russian_stemmer": {"type": "stemmer", "language": "russian"},
            "english_stop": {"type": "stop", "stopwords": "_english_"},
            "english_stemmer": {"type": "stemmer", "language": "english"},
        },
        "normalizer": {"kw_lower": {"type": "custom", "filter": ["lowercase"]}},
        "analyzer": {
            "quote": {
                "type": "custom",
                "char_filter": ["html_strip", "punct_strip"],
                "tokenizer": "standard",
                "filter": ["lowercase"],
            },
            "ru": {
                "type": "custom",
                "tokenizer": "standard",
                "filter": ["lowercase", "russian_stop", "russian_stemmer"],
            },
            "en": {
                "type": "custom",
                "tokenizer": "standard",
                "filter": ["lowercase", "english_stop", "english_stemmer"],
            },
        },
    }

    def meta_mappings():
        base = {
            "dynamic": "false",
            "properties": {
                "book_id": {"type": "keyword", "normalizer": "kw_lower"},
                "title": {
                    "type": "text",
                    "analyzer": "quote",
                    "fields": {
                        "raw": {"type": "keyword", "normalizer": "kw_lower"},
                        "ru": {"type": "text", "analyzer": "ru"},
                        "en": {"type": "text", "analyzer": "en"},
                    },
                },
                "author_names": {
                    "type": "text",
                    "analyzer": "quote",
                    "fields": {
                        "raw": {"type": "keyword", "normalizer": "kw_lower"},
                        "ru": {"type": "text", "analyzer": "ru"},
                        "en": {"type": "text", "analyzer": "en"},
                    },
                },
                "subjects": {
                    "type": "text",
                    "analyzer": "quote",
                    "fields": {"raw": {"type": "keyword", "normalizer": "kw_lower"}},
                },
                "publisher": {
                    "type": "text",
                    "analyzer": "quote",
                    "fields": {"raw": {"type": "keyword", "normalizer": "kw_lower"}},
                },
                "lang": {"type": "keyword", "normalizer": "kw_lower"},
                "pub_year": {"type": "integer"},
                "description": {
                    "type": "text",
                    "analyzer": "quote",
                    "fields": {
                        "ru": {"type": "text", "analyzer": "ru"},
                        "en": {"type": "text", "analyzer": "en"},
                    },
                },
            },
        }
        if enable_suggest:
            base["properties"]["title_suggest"] = {
                "type": "completion",
                "analyzer": "quote",
            }
            base["properties"]["author_suggest"] = {
                "type": "completion",
                "analyzer": "quote",
            }
        return base

    def content_mappings():
        props: dict[str, dict[str, Any]] = {
            "book_id": {"type": "keyword", "normalizer": "kw_lower"},
            "chapter_id": {"type": "long"},
            "chapter_ord": {"type": "integer"},
            "lang": {"type": "keyword", "normalizer": "kw_lower"},
            "title": {
                "type": "text",
                "analyzer": "quote",
                "fields": {
                    "raw": {"type": "keyword", "normalizer": "kw_lower"},
                    "ru": {"type": "text", "analyzer": "ru"},
                    "en": {"type": "text", "analyzer": "en"},
                },
            },
            "content": {
                "type": "text",
                "analyzer": "quote",
                "term_vector": "with_positions_offsets",
                "fields": {
                    "ru": {"type": "text", "analyzer": "ru"},
                    "en": {"type": "text", "analyzer": "en"},
                },
            },
            "length": {"type": "integer"},
            "block_start": {"type": "integer"},
            "block_end": {"type": "integer"},
            "block_offsets": {
                "type": "object",
                "enabled": True,
                "properties": {
                    "block_index": {"type": "integer"},
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                },
            },

            "para_type": {"type": "keyword"},
            "subchunk_idx": {"type": "integer"},
        }

        if dense_vec_dim and dense_vec_dim > 0:
            props["content_vec"] = {
                "type": "dense_vector",
                "dims": dense_vec_dim,
                "index": True,
                "similarity": "cosine",
            }

        return {
            "_source": {"enabled": store_source},
            "dynamic": "false",
            "properties": props,
        }

    if use_templates:
        tmpl_meta = {
            "index_patterns": ["books_meta*"],
            "template": {
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                    "analysis": analysis,
                },
                "mappings": meta_mappings(),
            },
            "priority": 10,
        }
        tmpl_content = {
            "index_patterns": ["books_content*"],
            "template": {"settings": {"analysis": analysis}, "mappings": content_mappings()},
            "priority": 10,
        }
        es_request("PUT", f"{es_url}/_index_template/books_meta_template", tmpl_meta)
        es_request("PUT", f"{es_url}/_index_template/books_content_template", tmpl_content)

    for name, mappings in [(idx_meta, meta_mappings()), (idx_content, content_mappings())]:
        r = requests.get(f"{es_url}/{name}", timeout=15)
        if r.status_code == 404:
            body = {
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                    "analysis": analysis,
                },
                "mappings": mappings,
            }
            es_request("PUT", f"{es_url}/{name}", body)
        elif r.status_code >= 400:
            raise RuntimeError(f"ES check index {name} failed: {r.status_code} {r.text[:500]}")


def es_bulk(es_url: str, index: str, docs: List[Dict], id_field: Optional[str] = None, chunk_size: int = 2000):
    import gzip

    def gen_actions(batch):
        lines = []
        for d in batch:
            if id_field and id_field in d:
                _id = d[id_field]
                src = {k: v for k, v in d.items() if k != id_field}
                meta = {"index": {"_index": index, "_id": _id}}
            else:
                src = d
                meta = {"index": {"_index": index}}
            lines.append(json.dumps(meta, ensure_ascii=False))
            lines.append(json.dumps(src, ensure_ascii=False))
        return ("\n".join(lines) + "\n").encode("utf-8")

    for i in range(0, len(docs), chunk_size):
        batch = docs[i : i + chunk_size]
        data = gen_actions(batch)
        headers = {"Content-Type": "application/x-ndjson", "Content-Encoding": "gzip"}
        r = requests.post(f"{es_url}/_bulk", data=gzip.compress(data), headers=headers, timeout=120)
        if r.status_code >= 400 or '"errors":true' in r.text:
            raise RuntimeError(f"ES bulk failed: {r.status_code} {r.text[:1000]}")


def es_bulk_safe(es_url: str, idx_meta: str, idx_content: str, meta_doc: Dict, content_docs: List[Dict]):
    if meta_doc:
        try:
            es_bulk(es_url, idx_meta, [meta_doc], id_field="book_id", chunk_size=1)
        except Exception as e:
            print(f"[WARN] ES meta bulk failed for book {meta_doc.get('book_id')}: {e}")
    if content_docs:
        try:
            es_bulk(es_url, idx_content, content_docs, id_field="_id", chunk_size=1000)
        except Exception as e:
            print(f"[WARN] ES content bulk failed: {e}")