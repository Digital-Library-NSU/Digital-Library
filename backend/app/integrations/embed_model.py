from typing import List, Optional
try:
    from sentence_transformers import SentenceTransformer
    _HAS_ST = True
except Exception:
    _HAS_ST = False

from app.config import EMBED_ADD_QUERY_PREFIX, EMBED_DEVICE, EMBED_MODEL, EMBED_NORMALIZE
_encoder: Optional[SentenceTransformer] = None
_encoder_dim: Optional[int] = None


def _pick_device() -> str:
    if EMBED_DEVICE in ("cpu", "cuda"):
        return EMBED_DEVICE
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def get_encoder() -> tuple[SentenceTransformer, int, str]:
    global _encoder, _encoder_dim
    if not _HAS_ST:
        raise Exception(500, "sentence-transformers is not installed")
    if _encoder is None:
        dev = _pick_device()
        enc = SentenceTransformer(EMBED_MODEL, device=dev)
        # Определим размерность
        test_emb = enc.encode(["test"], normalize_embeddings=EMBED_NORMALIZE)
        dim = len(test_emb[0])
        _encoder = enc
        _encoder_dim = dim
        print(
            f"[INFO] Semantic encoder ready: model={EMBED_MODEL}, dim={dim}, device={dev}, normalize={EMBED_NORMALIZE}")
    return _encoder, int(_encoder_dim or 0), _encoder._target_device.type


def encode_query(text: str) -> List[float]:
    enc, _, _ = get_encoder()
    q = text.strip()
    if EMBED_ADD_QUERY_PREFIX:
        q = f"query: {q}"
    vec = enc.encode([q], normalize_embeddings=EMBED_NORMALIZE)[0]
    return [float(x) for x in vec]
