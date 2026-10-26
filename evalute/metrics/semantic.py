import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer


def similarities(reference_texts, candidate_texts, model_name=None):
    texts = reference_texts + candidate_texts
    if not texts or not any(t.strip() for t in texts): return np.zeros((len(reference_texts), len(candidate_texts))), "empty"
    try:
        from sentence_transformers import SentenceTransformer
        vectors = SentenceTransformer(model_name).encode(texts, normalize_embeddings=True)
        matrix = np.asarray(vectors[:len(reference_texts)]) @ np.asarray(vectors[len(reference_texts):]).T
        return matrix, model_name
    except Exception:
        vectors = TfidfVectorizer(stop_words="english").fit_transform(texts)
        matrix = (vectors[:len(reference_texts)] @ vectors[len(reference_texts):].T).toarray()
        return matrix, "tfidf_fallback"


def deck_cosine(reference, candidate, model_name):
    matrix, backend = similarities([reference], [candidate], model_name)
    return float(matrix[0, 0]) if matrix.size else 0.0, backend
