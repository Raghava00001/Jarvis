import time

_shared_model = None
_load_error = None  # set when loading failed; we don't retry on every call

def get_shared_embedding_model(model_name: str = "all-MiniLM-L6-v2"):
    global _shared_model, _load_error
    if _shared_model is None and _load_error is None:
        try:
            from sentence_transformers import SentenceTransformer
            print(f"[EMBEDDINGS] Initializing shared model: {model_name}...")
            start = time.time()
            _shared_model = SentenceTransformer(model_name)
            print(f"[EMBEDDINGS] Loaded shared model in {time.time() - start:.2f}s")
        except Exception as e:
            _load_error = f"{type(e).__name__}: {e}"
            print(f"[EMBEDDINGS] ERROR loading model (ML intent routing disabled): {_load_error}")
            _shared_model = None
    return _shared_model


def get_embedding_load_error():
    """Why the embedding model failed to load, or None."""
    return _load_error
