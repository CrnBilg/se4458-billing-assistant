from pathlib import Path

import pytest

from indexer import SearchIndex, analyze, load_or_build, parse_sections

DOC = Path(__file__).resolve().parent.parent / "docs" / "Mobile_Provider_Billing_Guide.md"


@pytest.fixture(scope="module")
def index():
    return SearchIndex.build(DOC)


def sections(results):
    return [r["section"] for r in results]


# ---- chunking ---------------------------------------------------------------------------
def test_every_numbered_section_becomes_a_chunk():
    _, chunks = parse_sections(DOC.read_text(encoding="utf-8"))
    found = {c.section for c in chunks}
    for expected in ["0", "1", "2.1", "2.2", "2.3", "3.1", "3.2", "3.3", "4.1", "4.2", "4.3",
                     "4.4", "5.1", "5.2", "5.3", "6.1", "6.2", "6.3", "7.1", "7.2", "7.3",
                     "8.1", "8.2", "8.3", "8.4", "9"]:
        assert expected in found
    assert len(found) == len(chunks), "section ids must be unique"


def test_document_id_and_headings_are_extracted():
    doc_id, chunks = parse_sections(DOC.read_text(encoding="utf-8"))
    assert doc_id == "MOB-BILLING-2026-01"
    by_section = {c.section: c for c in chunks}
    assert by_section["3.2"].heading == "Additional internet blocks"
    assert "$10" in by_section["3.2"].text


def test_no_empty_chunks_and_headings_in_code_fences_are_ignored():
    md = "# T\n\n**Document ID:** X-1\n\n## 1. One\ntext\n```\n## 2. Not a heading\n```\n"
    _, chunks = parse_sections(md)
    assert [c.section for c in chunks] == ["0", "1"]
    assert "Not a heading" in chunks[1].text


# ---- retrieval --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "query,expected_section",
    [
        ("extra internet cost", "3.2"),
        ("additional 10 GB block price", "3.2"),
        ("when is my bill due", "6.1"),
        ("how many free phone minutes", "2.1"),
        ("dispute window", "7.1"),
        ("can I pay only part of my bill", "8.3"),
        ("why is my bill higher", "8.2"),
        ("service restriction unpaid", "6.3"),
        ("payment confirmation before paying", "5.2"),
    ],
)
def test_relevant_section_is_in_top_3(index, query, expected_section):
    assert expected_section in sections(index.search(query, k=3))


def test_heading_match_outranks_passing_mention(index):
    assert index.search("due date", k=1)[0]["section"] == "6.1"


def test_synonym_expansion_maps_extra_data_charges_to_internet_blocks(index):
    assert "3.2" in sections(index.search("extra data charges", k=3))


def test_stemming_matches_word_forms():
    assert analyze("charged charges charge") == ["charg", "charg", "charg"]


def test_results_are_ranked_and_limited(index):
    results = index.search("internet", k=2)
    assert len(results) == 2
    assert results[0]["score"] >= results[1]["score"]


def test_nonsense_query_returns_nothing(index):
    assert index.search("zzqx blorptang", k=3) == []
    assert index.search("the of and", k=3) == []  # only stop words


# ---- persistence and "index once" -------------------------------------------------------
def test_save_and_load_roundtrip_gives_identical_results(index, tmp_path):
    path = tmp_path / "idx.json"
    index.save(path)
    loaded = SearchIndex.load(path)
    assert loaded.search("extra internet cost") == index.search("extra internet cost")
    assert loaded.source_sha256 == index.source_sha256


def test_load_or_build_reuses_saved_index_and_rebuilds_when_document_changes(tmp_path):
    doc = tmp_path / "guide.md"
    doc.write_text("# G\n\n**Document ID:** D-1\n\n## 1. Alpha\nfirst text\n", encoding="utf-8")
    idx_path = tmp_path / "index.json"

    first = load_or_build(doc, idx_path)
    assert idx_path.exists() and first.chunks[-1].heading == "Alpha"

    mtime = idx_path.stat().st_mtime_ns
    load_or_build(doc, idx_path)  # unchanged document -> loaded, not rebuilt
    assert idx_path.stat().st_mtime_ns == mtime

    doc.write_text("# G\n\n**Document ID:** D-1\n\n## 1. Beta\nsecond text\n", encoding="utf-8")
    rebuilt = load_or_build(doc, idx_path)  # changed document -> rebuilt
    assert rebuilt.chunks[-1].heading == "Beta"
    assert "Alpha" not in [c.heading for c in rebuilt.chunks]
