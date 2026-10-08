"""End-to-end demo against a running server.

    uv run python scripts/demo.py                          # all .pdf/.docx in .samples/
    uv run python scripts/demo.py --samples-dir contracts/ # another directory
    uv run python scripts/demo.py path/to/contract.pdf     # specific files
    uv run python scripts/demo.py --base-url http://localhost:8000

Uploads each contract, prints a summary (status, clauses, tokens, timing, warnings),
shows the clauses of the first upload, then exercises GET by id, the paginated list,
the clause_type filter and one error response.
"""

import argparse
import sys
import time
from pathlib import Path

import httpx

DEFAULT_SAMPLES_DIR = Path(".samples")  # gitignored: the sample contracts are not committed
SUPPORTED = {".pdf", ".docx"}
TIMEOUT_S = 600.0  # long contracts take a while: the endpoint is synchronous


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", type=Path, help="contracts to upload")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--show-clauses", type=int, default=15, help="clauses to print")
    parser.add_argument(
        "--samples-dir",
        type=Path,
        default=DEFAULT_SAMPLES_DIR,
        help="directory of .pdf/.docx contracts, used when no files are given",
    )
    args = parser.parse_args()

    files = args.files or _sample_files(args.samples_dir)
    with httpx.Client(base_url=args.base_url, timeout=TIMEOUT_S) as client:
        _check_health(client)
        results = [_upload(client, path) for path in files]
        uploaded = [r for r in results if r is not None]
        if not uploaded:
            return 1
        _print_clauses(uploaded[0], args.show_clauses)
        _show_read_endpoints(client, uploaded[0]["document_id"])
        _show_error(client)
    return 0


def _sample_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        sys.exit(
            f"Samples directory '{directory}' not found. The sample contracts are not in the "
            "repository (.samples/ is gitignored): put .pdf/.docx files there, pass "
            "--samples-dir <dir>, or pass file paths directly."
        )
    files = sorted(p for p in directory.iterdir() if p.suffix.lower() in SUPPORTED)
    if not files:
        sys.exit(f"No .pdf or .docx files in '{directory}'.")
    return files


def _check_health(client: httpx.Client) -> None:
    try:
        client.get("/health").raise_for_status()
    except httpx.HTTPError as exc:
        sys.exit(f"Server not reachable at {client.base_url}: {exc}")


def _upload(client: httpx.Client, path: Path) -> dict | None:
    print(f"\n=== POST /api/extract  {path.name}")
    started = time.perf_counter()
    with path.open("rb") as handle:
        response = client.post("/api/extract", files={"file": (path.name, handle)})
    elapsed = time.perf_counter() - started
    body = response.json()
    if response.status_code != 201:
        print(f"  {response.status_code} {body['error']['code']}: {body['error']['message']}")
        return None

    review = sum(c["needs_review"] for c in body["clauses"])
    types = sorted({c["clause_type"] for c in body["clauses"]})
    print(
        f"  {response.status_code} status={body['status']}  pages={body['page_count']}  "
        f"clauses={body['clause_count']}  needs_review={review}"
    )
    print(
        f"  wall={elapsed:.1f}s  server={body['processing_ms'] / 1000:.1f}s  "
        f"tokens in/out={body['input_tokens']}/{body['output_tokens']}  model={body['model']}"
    )
    print(f"  types: {', '.join(types)}")
    for warning in body["warnings"]:
        print(f"  WARNING {warning['code']}: {warning['message']}")
    return body


def _print_clauses(extraction: dict, limit: int) -> None:
    print(f"\n=== Clauses of {extraction['filename']} (first {limit})")
    for clause in extraction["clauses"][:limit]:
        pages = f"p{clause['start_page']}-{clause['end_page']}" if clause["start_page"] else "-"
        flag = " [REVIEW: " + ", ".join(clause["issues"]) + "]" if clause["needs_review"] else ""
        preview = " ".join(clause["text"].split())[:70]
        print(
            f"  {clause['number'] or '-':>10}  {clause['clause_type']:<22} {pages:<8} "
            f"{preview}{flag}"
        )


def _show_read_endpoints(client: httpx.Client, document_id: str) -> None:
    print(f"\n=== GET /api/extractions/{document_id}")
    one = client.get(f"/api/extractions/{document_id}")
    print(f"  {one.status_code}  clauses={len(one.json()['clauses'])}")

    print("\n=== GET /api/extractions?page=1&page_size=3")
    page = client.get("/api/extractions", params={"page": 1, "page_size": 3}).json()
    print(f"  total={page['total']}")
    for item in page["items"]:
        print(f"  {item['created_at'][:19]}  {item['status']:<9} {item['filename'][:60]}")

    print("\n=== GET /api/extractions?clause_type=governing_law")
    filtered = client.get("/api/extractions", params={"clause_type": "governing_law"}).json()
    print(f"  total={filtered['total']}")


def _show_error(client: httpx.Client) -> None:
    print("\n=== POST /api/extract with a .txt file (expect 415)")
    response = client.post("/api/extract", files={"file": ("notes.txt", b"not a contract")})
    print(f"  {response.status_code} {response.json()}")


if __name__ == "__main__":
    sys.exit(main())
