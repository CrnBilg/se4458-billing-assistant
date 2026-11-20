"""Build the search index ahead of time and print how the guide was chunked.

    python build_index.py
"""
import os
from pathlib import Path

from indexer import SearchIndex

BASE = Path(__file__).resolve().parent
DOC_PATH = Path(os.getenv("BILLING_DOC_PATH", BASE / "docs" / "Mobile_Provider_Billing_Guide.md"))
INDEX_PATH = Path(os.getenv("BILLING_INDEX_PATH", BASE / "index" / "billing_index.json"))

if __name__ == "__main__":
    index = SearchIndex.build(DOC_PATH)
    index.save(INDEX_PATH)
    print(f"Document : {index.document} ({index.document_id})")
    print(f"Chunks   : {len(index.chunks)}   Unique terms: {len(index.postings)}   "
          f"Avg length: {index.avgdl:.1f} tokens")
    print(f"Index    : {INDEX_PATH}\n")
    print(f"{'section':<8} {'tokens':>6}  heading")
    for chunk, length in zip(index.chunks, index.doc_len):
        print(f"{chunk.section:<8} {length:>6}  {chunk.heading}")
