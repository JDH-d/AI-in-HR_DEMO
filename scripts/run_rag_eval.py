from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from rag.index import build_index_items
from rag.retriever import Retriever
from services.document_reader import load_documents

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "evals" / "rag_questions.json"
DEFAULT_DOCUMENTS = ROOT / "documents"


def load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases", [])
    if not isinstance(cases, list):
        raise ValueError("Evaluation dataset must contain a cases list")
    return cases


def evaluate_cases(
    cases: list[dict[str, Any]],
    documents_dir: Path,
    *,
    use_embeddings: bool = False,
) -> dict[str, Any]:
    documents = load_documents(documents_dir)
    items = build_index_items(documents, include_embeddings=use_embeddings)
    retrieval_mode = (
        "embedding" if items and all(item.get("embedding") for item in items) else "lexical"
    )
    retriever = Retriever(items)
    results: list[dict[str, Any]] = []

    for case in cases:
        retrieved = retriever.query(
            case["question"],
            top_k=3,
            min_similarity=0.2,
            use_embeddings=use_embeddings,
        )
        expected_source = case["expected_source"]
        expected_terms = [str(term).lower() for term in case.get("expected_terms", [])]
        source_matches = [result for result in retrieved if result["source"] == expected_source]
        matching = next(
            (
                result
                for result in source_matches
                if all(term in result["excerpt"].lower() for term in expected_terms)
            ),
            source_matches[0] if source_matches else None,
        )
        excerpt = (matching or {}).get("excerpt", "")
        missing_terms = [term for term in expected_terms if term not in excerpt.lower()]
        passed = matching is not None and not missing_terms
        results.append(
            {
                "id": case["id"],
                "passed": passed,
                "expected_source": expected_source,
                "retrieved_sources": [result["source"] for result in retrieved],
                "missing_terms": missing_terms,
                "excerpt": excerpt,
            }
        )

    passed_count = sum(1 for result in results if result["passed"])
    total = len(results)
    return {
        "passed": passed_count,
        "total": total,
        "pass_rate": passed_count / total if total else 0.0,
        "retrieval_mode": retrieval_mode,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic RAG retrieval evaluation.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS)
    parser.add_argument("--min-pass-rate", type=float, default=1.0)
    parser.add_argument(
        "--use-embeddings",
        action="store_true",
        help="Exercise the configured embedding model instead of the deterministic lexical path.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    report = evaluate_cases(
        load_cases(args.dataset),
        args.documents,
        use_embeddings=args.use_embeddings,
    )
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"RAG evaluation [{report['retrieval_mode']}]: "
            f"{report['passed']}/{report['total']} ({report['pass_rate']:.1%})"
        )
        for result in report["results"]:
            if not result["passed"]:
                print(
                    f"- FAIL {result['id']}: sources={result['retrieved_sources']} "
                    f"missing={result['missing_terms']}"
                )
    if args.use_embeddings and report["retrieval_mode"] != "embedding":
        print("Embedding evaluation was requested, but embeddings could not be created.")
        return 2
    return 0 if report["pass_rate"] >= args.min_pass_rate else 1


if __name__ == "__main__":
    raise SystemExit(main())
