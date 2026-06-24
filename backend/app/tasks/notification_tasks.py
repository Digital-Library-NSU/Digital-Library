from collections import defaultdict
from email.message import EmailMessage
import smtplib
from typing import Any

import psycopg2
import requests

from app.celery_app import celery_app
from app.config import (
    ES_PASS,
    ES_URL,
    ES_USER,
    IDX_CONTENT,
    IDX_META,
    PG_DSN,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USE_TLS,
    SMTP_USER,
)


print("[INFO] Notification tasks loaded without embedding model preload")

RECOMMENDATION_SOURCE_LIMIT = 5
RECOMMENDATION_CANDIDATE_POOL_SIZE = 50
RECOMMENDATION_MIN_SEMANTIC_SCORE = 0.75
RECOMMENDATION_RELATIVE_SCORE_RATIO = 0.95
RECOMMENDATION_CONTENT_POOL_SIZE = 300


def _es_auth() -> tuple[str, str] | None:
    if ES_USER and ES_PASS:
        return ES_USER, ES_PASS
    return None


def _es_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(
        f"{ES_URL.rstrip('/')}/{path.lstrip('/')}",
        json=payload,
        auth=_es_auth(),
        headers={"Content-Type": "application/json"},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def _extract_book_vec(hit: dict[str, Any]) -> list[float] | None:
    source_vec = hit.get("_source", {}).get("book_vec")
    if source_vec:
        return source_vec

    field_vec = hit.get("fields", {}).get("book_vec")
    if isinstance(field_vec, list) and field_vec:
        first = field_vec[0]
        if isinstance(first, list):
            return first

    return None


def _extract_book_id(hit: dict[str, Any]) -> int | None:
    source_book_id = hit.get("_source", {}).get("book_id")
    raw_book_id = source_book_id if source_book_id is not None else hit.get("_id")

    try:
        return int(raw_book_id)
    except Exception:
        return None


def _get_book_vectors(book_ids: list[int]) -> dict[int, list[float]]:
    if not book_ids:
        return {}

    res = _es_post(
        f"{IDX_META}/_search",
        {
            "size": len(book_ids),
            "query": {"ids": {"values": [str(book_id) for book_id in book_ids]}},
            "_source": ["book_id", "book_vec"],
            "fields": ["book_vec"],
        },
    )

    vectors: dict[int, list[float]] = {}
    for hit in res.get("hits", {}).get("hits", []):
        book_id = _extract_book_id(hit)
        if book_id is None:
            continue

        vec = _extract_book_vec(hit)
        if vec:
            vectors[book_id] = [float(value) for value in vec]

    return vectors


def _average_vectors(vectors: list[list[float]]) -> list[float] | None:
    if not vectors:
        return None

    dim = len(vectors[0])
    sums = [0.0] * dim
    valid_count = 0

    for vec in vectors:
        if len(vec) != dim:
            continue

        for idx, value in enumerate(vec):
            sums[idx] += float(value)
        valid_count += 1

    if valid_count == 0:
        return None

    mean = [value / valid_count for value in sums]
    norm = sum(value * value for value in mean) ** 0.5
    if norm <= 0:
        return None

    return [value / norm for value in mean]


def _normalize_terms(values: list[str] | None) -> set[str]:
    if not values:
        return set()

    return {
        value.strip().lower()
        for value in values
        if value and value.strip()
    }


def _filter_recommendation_candidates(
    candidates: list[tuple[int, float]],
) -> list[tuple[int, float]]:
    if not candidates:
        return []

    sorted_candidates = sorted(candidates, key=lambda item: item[1], reverse=True)
    best_score = sorted_candidates[0][1]
    relative_threshold = best_score * RECOMMENDATION_RELATIVE_SCORE_RATIO

    return [
        (book_id, score)
        for book_id, score in sorted_candidates
        if score >= relative_threshold
    ]


def _recommendation_metadata_scores(
    source_book_ids: list[int],
    candidate_ids: list[int],
) -> dict[int, dict[str, float | str]]:
    all_book_ids = sorted(set(source_book_ids + candidate_ids))
    if not all_book_ids:
        return {}

    with psycopg2.connect(PG_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, authors, subjects
                FROM books
                WHERE id = ANY(%s)
                """,
                (all_book_ids,),
            )
            rows = cur.fetchall()

    meta_by_id: dict[int, dict[str, Any]] = {
        int(row[0]): {
            "title": row[1],
            "authors": _normalize_terms(row[2]),
            "subjects": _normalize_terms(row[3]),
        }
        for row in rows
    }

    source_authors: set[str] = set()
    source_subjects: set[str] = set()
    for book_id in source_book_ids:
        source_meta = meta_by_id.get(book_id)
        if not source_meta:
            continue

        source_authors.update(source_meta["authors"])
        source_subjects.update(source_meta["subjects"])

    scores: dict[int, dict[str, float | str]] = {}
    for book_id in candidate_ids:
        candidate_meta = meta_by_id.get(book_id)
        if not candidate_meta:
            continue

        candidate_authors = candidate_meta["authors"]
        candidate_subjects = candidate_meta["subjects"]
        author_score = 1.0 if source_authors & candidate_authors else 0.0
        subject_union = source_subjects | candidate_subjects
        subject_score = (
            len(source_subjects & candidate_subjects) / len(subject_union)
            if subject_union
            else 0.0
        )

        scores[book_id] = {
            "title": str(candidate_meta["title"]),
            "meta_score": author_score * 0.80 + subject_score * 0.20,
        }

    return scores


def _content_scores_for_recommendations(
    user_vec: list[float],
    candidate_ids: list[int],
    excluded_book_ids: list[int],
) -> dict[int, dict[str, float]]:
    if not candidate_ids:
        return {}

    content_pool_size = max(
        RECOMMENDATION_CONTENT_POOL_SIZE,
        len(candidate_ids) * 20,
    )
    res = _es_post(
        f"{IDX_CONTENT}/_search",
        {
            "size": content_pool_size,
            "knn": {
                "field": "content_vec",
                "query_vector": user_vec,
                "k": content_pool_size,
                "num_candidates": max(500, content_pool_size * 10),
                "filter": {
                    "bool": {
                        "filter": [
                            {
                                "terms": {
                                    "book_id": [
                                        str(book_id)
                                        for book_id in candidate_ids
                                    ]
                                }
                            }
                        ],
                        "must_not": [
                            {
                                "terms": {
                                    "book_id": [
                                        str(book_id)
                                        for book_id in excluded_book_ids
                                    ]
                                }
                            }
                        ],
                    }
                },
            },
            "_source": ["book_id"],
        },
    )

    scores: dict[int, dict[str, float]] = {}
    for hit in res.get("hits", {}).get("hits", []):
        try:
            book_id = int(hit.get("_source", {}).get("book_id"))
        except Exception:
            continue

        score = float(hit.get("_score") or 0.0)
        current = scores.setdefault(
            book_id,
            {
                "max_score": 0.0,
                "sum_score": 0.0,
                "hits_count": 0.0,
            },
        )
        current["max_score"] = max(current["max_score"], score)
        current["sum_score"] += score
        current["hits_count"] += 1.0

    return scores


def _rank_recommendations_semantically(
    user_vec: list[float],
    candidates: list[tuple[int, float]],
    excluded_book_ids: list[int],
    source_book_ids: list[int],
) -> list[int]:
    filtered_candidates = _filter_recommendation_candidates(candidates)
    if not filtered_candidates:
        return []

    candidate_ids = [book_id for book_id, _score in filtered_candidates]
    metadata_scores = _recommendation_metadata_scores(source_book_ids, candidate_ids)
    content_scores = _content_scores_for_recommendations(
        user_vec,
        candidate_ids,
        excluded_book_ids,
    )

    if not content_scores:
        return candidate_ids

    max_book_score = max(score for _book_id, score in filtered_candidates)
    max_content_score = max(score["max_score"] for score in content_scores.values())
    max_hits_count = max(score["hits_count"] for score in content_scores.values())

    ranked: list[tuple[int, float]] = []
    for book_id, book_score in filtered_candidates:
        content_score = content_scores.get(book_id)
        if content_score is None:
            continue

        metadata_score = metadata_scores.get(book_id, {})
        book_norm = book_score / max_book_score if max_book_score > 0 else 0.0
        content_norm = (
            content_score["max_score"] / max_content_score
            if max_content_score > 0
            else 0.0
        )
        content_hits_norm = (
            content_score["hits_count"] / max_hits_count
            if max_hits_count > 0
            else 0.0
        )
        meta_score = float(metadata_score.get("meta_score", 0.0))
        final_score = (
            book_norm * 0.35
            + content_norm * 0.40
            + content_hits_norm * 0.10
            + meta_score * 0.15
        )
        ranked.append((book_id, final_score))

    ranked.sort(key=lambda item: item[1], reverse=True)
    return [book_id for book_id, _score in ranked]


def _recommended_ids_for_user(
    source_book_ids: list[int],
    excluded_book_ids: list[int],
) -> list[int]:
    source_vectors = list(_get_book_vectors(source_book_ids).values())
    user_vec = _average_vectors(source_vectors)
    if user_vec is None:
        return []

    search_size = RECOMMENDATION_CANDIDATE_POOL_SIZE + len(excluded_book_ids)
    rec_res = _es_post(
        f"{IDX_META}/_search",
        {
            "size": search_size,
            "min_score": RECOMMENDATION_MIN_SEMANTIC_SCORE,
            "knn": {
                "field": "book_vec",
                "query_vector": user_vec,
                "k": search_size,
                "num_candidates": max(100, search_size * 20),
            },
            "_source": ["book_id"],
        },
    )

    excluded_book_ids_set = set(excluded_book_ids)
    candidates: list[tuple[int, float]] = []
    for hit in rec_res.get("hits", {}).get("hits", []):
        book_id = _extract_book_id(hit)
        if book_id is None or book_id in excluded_book_ids_set:
            continue

        candidates.append((book_id, float(hit.get("_score") or 0.0)))

    ranked_ids = _rank_recommendations_semantically(
        user_vec,
        candidates,
        excluded_book_ids,
        source_book_ids,
    )
    return ranked_ids


def _fetch_notification_candidates(new_book_id: int) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    with psycopg2.connect(PG_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, authors
                FROM books
                WHERE id = %s
                """,
                (new_book_id,),
            )
            book_row = cur.fetchone()
            if book_row is None:
                return {}, {}

            cur.execute(
                """
                SELECT u.id::text, u.email, u.login, rp.book_id
                FROM users u
                JOIN reading_progress rp ON rp.user_id = u.id
                WHERE u.notify_recommendations = true
                  AND u.email IS NOT NULL
                  AND rp.book_id <> %s
                ORDER BY u.id, rp.updated_at DESC
                """,
                (new_book_id,),
            )
            progress_rows = cur.fetchall()

    book = {
        "id": int(book_row[0]),
        "title": book_row[1],
        "authors": book_row[2] or [],
    }

    users: dict[str, dict[str, Any]] = {}
    source_book_ids_by_user: dict[str, list[int]] = defaultdict(list)
    excluded_book_ids_by_user: dict[str, list[int]] = defaultdict(list)

    for user_id, email, login, source_book_id in progress_rows:
        users[user_id] = {
            "email": email,
            "login": login,
        }

        excluded_book_ids_by_user[user_id].append(int(source_book_id))
        source_ids = source_book_ids_by_user[user_id]
        if len(source_ids) < RECOMMENDATION_SOURCE_LIMIT:
            source_ids.append(int(source_book_id))

    return book, {
        user_id: {
            "user_id": user_id,
            "email": users[user_id]["email"],
            "login": users[user_id]["login"],
            "source_book_ids": source_book_ids,
            "excluded_book_ids": excluded_book_ids_by_user[user_id],
        }
        for user_id, source_book_ids in source_book_ids_by_user.items()
    }


def _send_email(to_email: str, subject: str, body: str) -> None:
    if not SMTP_HOST:
        print(
            "[notifications:email:dry-run] "
            f"to={to_email!r} subject={subject!r} body={body!r}"
        )
        return

    message = EmailMessage()
    message["From"] = SMTP_FROM
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        if SMTP_USE_TLS:
            smtp.starttls()
        if SMTP_USER and SMTP_PASSWORD:
            smtp.login(SMTP_USER, SMTP_PASSWORD)
        smtp.send_message(message)


def _store_sent_recommendation(user_id: str, book_id: int, score: float) -> None:
    with psycopg2.connect(PG_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO recommendation_notifications (user_id, book_id, score)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, book_id)
                DO UPDATE SET score = EXCLUDED.score, sent_at = now()
                """,
                (user_id, book_id, score),
            )


@celery_app.task(name="notifications.new_book_recommendations")
def notify_new_book_recommendations(new_book_id: int) -> dict[str, int]:
    book, users = _fetch_notification_candidates(new_book_id)
    if not book or not users:
        return {"checked": 0, "sent": 0}

    checked = 0
    sent = 0
    authors = ", ".join(book["authors"] or [])

    for user in users.values():
        checked += 1

        recommended_ids = _recommended_ids_for_user(
            user["source_book_ids"],
            user["excluded_book_ids"],
        )
        if new_book_id not in recommended_ids:
            continue

        rank = recommended_ids.index(new_book_id) + 1
        score = 1.0 / rank
        subject = f"Новая книга для вас: {book['title']}"
        body = (
            f"Здравствуйте, {user['login']}!\n\n"
            "В библиотеку добавлена книга, которая попала в ваши рекомендации:\n"
            f"{book['title']}"
            f"{f' — {authors}' if authors else ''}\n\n"
            f"Позиция в текущих рекомендациях: {rank}."
        )

        _store_sent_recommendation(user["user_id"], new_book_id, score)
        _send_email(user["email"], subject, body)
        sent += 1

        print(
            "[notifications:recommendation] "
            f"user={user['login']!r} email={user['email']!r} "
            f"book_id={new_book_id} rank={rank}"
        )

    return {"checked": checked, "sent": sent}


@celery_app.task(name="notifications.ping")
def notification_ping() -> str:
    return "ok"
