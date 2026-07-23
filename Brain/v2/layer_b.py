# V2 Layer B is identical to V1 -- rule-based extraction + BGE-M3 embeddings.
from v1.layer_b import extract_pairs, assign_scenarios, embed_and_store_pairs  # noqa: F401

__all__ = ["extract_pairs", "assign_scenarios", "embed_and_store_pairs"]
