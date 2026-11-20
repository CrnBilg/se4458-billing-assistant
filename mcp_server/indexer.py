"""Chunk the billing guide by section and build a BM25 full-text index.

Pipeline (run once, before any question is asked):
    Markdown file --parse_sections--> section chunks --SearchIndex.build--> inverted index (JSON)

* One chunk per numbered section/sub-section ("2.1", "3.2", "8.3", ...), so a hit always carries
  an exact section reference the agent can cite.
* Heading words are counted three times when indexing, so a query that matches a heading ranks
  above one that only mentions the words in passing.
* Terms are stemmed (charge/charged/charges -> "charg") and a few billing synonyms are expanded
  at query time (extra -> additional, data -> internet, ...).
* Ranking is Okapi BM25. No embeddings and no external service are needed.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import snowballstemmer

INDEX_VERSION = 1
HEADING_BOOST = 3
BM25_K1 = 1.5
BM25_B = 0.75

_STEMMER = snowballstemmer.stemmer("english")

STOPWORDS = frozenset(
    """a an and are as at be by can do does for from how i if in is it its me my of on or our so
    than that the their then there this to was what when where which who why will with you your
    should must may""".split()
)

# Query-time expansion: user wording -> wording used in the guide.
SYNONYMS = {
    "extra": ["additional"],
    "data": ["internet"],
    "pay": ["payment"],
    "paying": ["payment"],
    "paid": ["payment"],
    "cost": ["price"],
    "costs": ["price"],
    "expensive": ["price"],
    "overage": ["additional"],
    "complaint": ["dispute"],
    "complain": ["dispute"],
    "overdue": ["late"],
    "calls": ["phone"],
    "call": ["phone"],
    "gb": ["internet"],
    "mb": ["internet"],
}
SYNONYM_WEIGHT = 0.6

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_SECTION_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.*)$")
_DOC_ID_RE = re.compile(r"\*\*Document ID:\*\*\s*(\S+)")
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True)
class Chunk:
    section: str  # "3.2"; "0" is the document preamble
    heading: str  # "Additional internet blocks"
    text: str


def analyze(text: str) -> list[str]:
    """Lowercase, split into words, drop stop words, stem."""
    words = (w.lower() for w in _WORD_RE.findall(text))
    return [_STEMMER.stemWord(w) for w in words if w not in STOPWORDS]


def parse_sections(markdown: str) -> tuple[str, list[Chunk]]:
    """Return (document_id, chunks). Headings inside code fences are ignored."""
    doc_match = _DOC_ID_RE.search(markdown)
    document_id = doc_match.group(1) if doc_match else "UNKNOWN"

    chunks: list[Chunk] = []
    section, heading, buf = "0", "Document overview", []
    in_fence = False

    def flush():
        text = "\n".join(buf).strip()
        if text:
            chunks.append(Chunk(section=section, heading=heading, text=text))

    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        m = None if in_fence else _HEADING_RE.match(line)
        if m and len(m.group(1)) >= 2:
            sec = _SECTION_RE.match(m.group(2))
            if sec:  # a numbered section starts a new chunk
                flush()
                section, heading, buf = sec.group(1), sec.group(2).strip(), []
                continue
        buf.append(line)
    flush()
    return document_id, chunks


class SearchIndex:
    def __init__(self, document: str, document_id: str, source_sha256: str,
                 chunks: list[Chunk], postings: dict, doc_len: list[int]):
        self.document = document
        self.document_id = document_id
        self.source_sha256 = source_sha256
        self.chunks = chunks
        self.postings = postings  # term -> {chunk_index(str): term_frequency}
        self.doc_len = doc_len
        self.avgdl = (sum(doc_len) / len(doc_len)) if doc_len else 0.0

    # ---- build / persist -------------------------------------------------
    @classmethod
    def build(cls, markdown_path: Path) -> "SearchIndex":
        raw = markdown_path.read_bytes()
        document_id, chunks = parse_sections(raw.decode("utf-8"))
        postings: dict[str, dict[str, int]] = {}
        doc_len: list[int] = []
        for i, chunk in enumerate(chunks):
            tokens = analyze(chunk.text) + analyze(chunk.heading) * HEADING_BOOST
            doc_len.append(len(tokens))
            for term, tf in Counter(tokens).items():
                postings.setdefault(term, {})[str(i)] = tf
        return cls(markdown_path.name, document_id, hashlib.sha256(raw).hexdigest(),
                   chunks, postings, doc_len)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": INDEX_VERSION,
            "document": self.document,
            "document_id": self.document_id,
            "source_sha256": self.source_sha256,
            "chunks": [asdict(c) for c in self.chunks],
            "doc_len": self.doc_len,
            "postings": self.postings,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "SearchIndex":
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != INDEX_VERSION:
            raise ValueError("index version mismatch")
        return cls(
            data["document"], data["document_id"], data["source_sha256"],
            [Chunk(**c) for c in data["chunks"]], data["postings"], data["doc_len"],
        )

    # ---- query -----------------------------------------------------------
    def _query_terms(self, query: str) -> dict[str, float]:
        weights: dict[str, float] = {}
        for raw in (w.lower() for w in _WORD_RE.findall(query)):
            if raw in STOPWORDS:
                continue
            weights[_STEMMER.stemWord(raw)] = 1.0
            for syn in SYNONYMS.get(raw, []):
                stem = _STEMMER.stemWord(syn)
                weights.setdefault(stem, SYNONYM_WEIGHT)
        return weights

    def search(self, query: str, k: int = 3) -> list[dict]:
        n = len(self.chunks)
        scores: dict[int, float] = {}
        for term, weight in self._query_terms(query).items():
            posting = self.postings.get(term)
            if not posting:
                continue
            idf = math.log(1 + (n - len(posting) + 0.5) / (len(posting) + 0.5))
            for idx_str, tf in posting.items():
                idx = int(idx_str)
                norm = 1 - BM25_B + BM25_B * self.doc_len[idx] / self.avgdl
                scores[idx] = scores.get(idx, 0.0) + weight * idf * (
                    tf * (BM25_K1 + 1) / (tf + BM25_K1 * norm)
                )
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
        return [
            {
                "section": self.chunks[i].section,
                "heading": self.chunks[i].heading,
                "text": self.chunks[i].text,
                "score": round(score, 3),
            }
            for i, score in ranked
        ]


def load_or_build(markdown_path: Path, index_path: Path) -> SearchIndex:
    """Use the saved index when it matches the document; otherwise (re)build and save it.
    Called once at server start-up -- questions never trigger indexing."""
    if index_path.exists():
        try:
            idx = SearchIndex.load(index_path)
            if idx.source_sha256 == hashlib.sha256(markdown_path.read_bytes()).hexdigest():
                return idx
        except (ValueError, KeyError, json.JSONDecodeError):
            pass
    idx = SearchIndex.build(markdown_path)
    idx.save(index_path)
    return idx
