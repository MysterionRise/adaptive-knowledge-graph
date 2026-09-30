"""
Data pipeline and developer-experience scripts (multi-subject, see config/subjects.yaml).

- ingest_books.py: fetch OpenStax books into data/processed/books_<subject>.jsonl
- build_knowledge_graph.py, create_neo4j_indexes.py: build the Neo4j graph and its indexes
- index_to_opensearch.py: chunk, embed and index the text for retrieval
- build_chunk_windows.py: Neo4j Chunk nodes with NEXT edges for window retrieval
- seed_student_profile.py: demo learner profile (SQLite)
- evaluate_rag.py, check_demo_eval.py: live KG-RAG evaluation and its gate
- stack_check.py plus the *.sh scripts: quickstart, doctor, seeding and demo helpers
"""
