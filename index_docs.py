#!/usr/bin/env python3
"""
index_docs.py — Chunk markdown docs and index them into a ChromaDB
vector store using local sentence-transformer embeddings.

Usage:
    python index_docs.py [--input-dir DIR] [--db-dir DIR]
"""

import re
import sys
import yaml
import argparse
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                meta = {}
            return meta, parts[2].strip()
    return {}, text


def strip_markdown(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"`[^`]+`", "", text)
    text = re.sub(r"---+", "", text)
    return text.strip()


def chunk_by_heading(body: str) -> list[dict]:
    """Split markdown into chunks by ## headings."""
    chunks = []
    current_heading = "Introduction"
    current_lines = []

    for line in body.split("\n"):
        m = re.match(r"^(#{1,3})\s+(.+)", line)
        if m and current_lines:
            text = strip_markdown("\n".join(current_lines))
            if text and len(text) > 20:
                chunks.append({"heading": current_heading, "text": text})
            current_heading = m.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)

    # Last chunk
    if current_lines:
        text = strip_markdown("\n".join(current_lines))
        if text and len(text) > 20:
            chunks.append({"heading": current_heading, "text": text})

    # If no headings found, chunk the whole thing
    if not chunks:
        text = strip_markdown(body)
        if text and len(text) > 20:
            chunks.append({"heading": "Content", "text": text})

    return chunks


def main():
    parser = argparse.ArgumentParser(description="Index docs into ChromaDB")
    parser.add_argument("--input-dir", default="site/markdown")
    parser.add_argument("--db-dir", default="search_db")
    args = parser.parse_args()

    md_dir = Path(args.input_dir)
    db_dir = Path(args.db_dir)

    if not md_dir.exists():
        print(f"Error: {md_dir} not found")
        sys.exit(1)

    md_files = sorted(md_dir.glob("*.md"))
    print(f"Found {len(md_files)} markdown files")

    # Set up ChromaDB with local embeddings
    print("Initialising ChromaDB with sentence-transformer embeddings...")
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )

    client = chromadb.PersistentClient(path=str(db_dir))

    # Delete existing collection if re-indexing
    try:
        client.delete_collection("helpctr_docs")
    except Exception:
        pass

    collection = client.create_collection(
        name="helpctr_docs",
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )

    # Process all files
    all_ids = []
    all_docs = []
    all_metas = []
    total_chunks = 0

    for i, f in enumerate(md_files):
        raw = f.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(raw)

        title = meta.get("title", f.stem)
        collection_name = meta.get("collection", "")
        subcollection = meta.get("subcollection", "")
        source_url = meta.get("source_url", "")
        html_file = f.stem + ".html"

        chunks = chunk_by_heading(body)

        for j, chunk in enumerate(chunks):
            doc_id = f"{f.stem}__chunk{j}"
            text = f"{title} — {chunk['heading']}\n\n{chunk['text']}"

            all_ids.append(doc_id)
            all_docs.append(text)
            all_metas.append({
                "title": title,
                "heading": chunk["heading"],
                "collection": collection_name,
                "subcollection": subcollection,
                "source_url": source_url,
                "html_file": html_file,
                "file": f.name,
            })
            total_chunks += 1

        if (i + 1) % 50 == 0:
            print(f"  Chunked {i + 1}/{len(md_files)} files ({total_chunks} chunks)...")

    print(f"  Total: {total_chunks} chunks from {len(md_files)} files")

    # Batch insert (ChromaDB handles batching internally, but we limit to 500)
    print("Generating embeddings and indexing (this may take a few minutes)...")
    batch_size = 200
    for start in range(0, len(all_ids), batch_size):
        end = min(start + batch_size, len(all_ids))
        collection.add(
            ids=all_ids[start:end],
            documents=all_docs[start:end],
            metadatas=all_metas[start:end],
        )
        print(f"  Indexed {end}/{len(all_ids)} chunks...")

    print(f"\nDone! {total_chunks} chunks indexed in {db_dir}")
    print(f"Collection: helpctr_docs ({collection.count()} documents)")


if __name__ == "__main__":
    main()
