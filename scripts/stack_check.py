"""
Readiness and prerequisite probes shared by the shell scripts (quickstart, doctor, seeding).

Every subcommand prints a one-line summary (plus indented detail lines on problems) and exits
0 when the check passes and 1 when it does not (`index-fingerprint` exits 2 on warnings only).

    python scripts/stack_check.py ollama        # server reachable, model pulled, 1-token generation
    python scripts/stack_check.py node          # `node --version` satisfies frontend engines.node
    python scripts/stack_check.py python-range  # backend Python requirement from pyproject.toml
    python scripts/stack_check.py spacy         # spaCy model en_core_web_sm is installed
    python scripts/stack_check.py wait          # Neo4j (bolt) and OpenSearch are ready
    python scripts/stack_check.py seed-status --subject us_history   # prints "<concepts> <chunks>"
    python scripts/stack_check.py index-fingerprint us_history economics   # vectors still match

`ollama`, `node` and `python-range` only need the standard library, so `make doctor` can run them
before `poetry install`. `python-range` needs Python >=3.11 for `tomllib`. The other subcommands
need the backend dependencies (`poetry run python ...`).
Connection settings come from the backend settings (environment variables and `.env`) when they
can be imported, falling back to the environment and the backend defaults.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import operator as version_operator
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.1:8b-instruct-q4_K_M"
SPACY_MODEL = "en_core_web_sm"


def _report(summary: str, details: list[str] | None = None) -> None:
    print(summary)
    for line in details or []:
        print(f"    {line}")


def _truncate(text: str, limit: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


# ---------------------------------------------------------------------------
# Python requirement
# ---------------------------------------------------------------------------


def satisfies_python(version: str, requirement: str) -> bool:
    """Check comma-separated numeric Python comparisons; reject unknown syntax."""
    comparisons = {
        ">=": version_operator.ge,
        ">": version_operator.gt,
        "<=": version_operator.le,
        "<": version_operator.lt,
        "==": version_operator.eq,
        "!=": version_operator.ne,
    }

    def parts(value: str) -> tuple[int, ...]:
        if not re.fullmatch(r"\d+(?:\.\d+){0,2}", value):
            raise ValueError(f"invalid numeric Python version: {value!r}")
        numbers = tuple(int(part) for part in value.split("."))
        return numbers + (0,) * (3 - len(numbers))

    installed = parts(version)
    accepted = True
    for clause in requirement.split(","):
        match = re.fullmatch(r"\s*(>=|<=|==|!=|>|<)\s*(\d+(?:\.\d+){0,2})\s*", clause)
        if match is None:
            raise ValueError(
                "use comma-separated numeric comparisons (>=, >, <=, <, ==, !=); "
                f"unsupported clause: {clause!r}"
            )
        # Validate every clause, even if an earlier comparison already failed.
        accepted = comparisons[match[1]](installed, parts(match[2])) and accepted
    return accepted


def cmd_python_range(args: argparse.Namespace) -> int:
    """Print the declared Python range, optionally checking a candidate version."""
    try:
        # Keep the other stdlib probes usable on older Python bootstrap interpreters.
        import tomllib

        with (PROJECT_ROOT / "pyproject.toml").open("rb") as file:
            requirement = tomllib.load(file)["tool"]["poetry"]["dependencies"]["python"]
        if not isinstance(requirement, str):
            raise ValueError("tool.poetry.dependencies.python must be a string")
        accepted = satisfies_python(args.version or "0.0.0", requirement)
    except (ImportError, OSError, KeyError, TypeError, ValueError) as error:
        _report(f"Cannot read the Python requirement in pyproject.toml: {error}")
        return 1
    print(requirement)
    return 0 if args.version is None or accepted else 1


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@dataclass
class LLMConfig:
    mode: str
    ollama_host: str
    model: str


def _backend_settings() -> Any | None:
    """Return the backend settings object, or None when the backend is not importable."""
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from backend.app.core.settings import settings
    except Exception:
        return None
    return settings


def _llm_config() -> LLMConfig:
    settings = _backend_settings()
    if settings is not None:
        return LLMConfig(
            mode=str(settings.llm_mode),
            ollama_host=str(settings.llm_ollama_host),
            model=str(settings.llm_local_model),
        )
    return LLMConfig(
        mode=os.environ.get("LLM_MODE", "local"),
        ollama_host=os.environ.get("LLM_OLLAMA_HOST", DEFAULT_OLLAMA_HOST),
        model=os.environ.get("LLM_LOCAL_MODEL", DEFAULT_OLLAMA_MODEL),
    )


# ---------------------------------------------------------------------------
# HTTP helpers (standard library only)
# ---------------------------------------------------------------------------


def _http_json(
    url: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 5.0,
    auth: tuple[str, str] | None = None,
    context: ssl.SSLContext | None = None,
) -> tuple[int, dict[str, Any]]:
    """Send a GET (or a JSON POST when payload is given); return (status, decoded JSON body)."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if auth is not None:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    try:
        body = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        body = {"error": _truncate(raw.decode("utf-8", errors="replace"))}
    return status, body if isinstance(body, dict) else {"value": body}


# ---------------------------------------------------------------------------
# ollama
# ---------------------------------------------------------------------------

OLLAMA_SKIP_HINT = (
    "Set SKIP_OLLAMA_CHECK=1 to skip this check (answers and quizzes need a working LLM)."
)


def cmd_ollama(args: argparse.Namespace) -> int:
    if os.environ.get("SKIP_OLLAMA_CHECK") == "1":
        _report("Ollama check skipped (SKIP_OLLAMA_CHECK=1)")
        return 0

    config = _llm_config()
    if config.mode == "remote":
        _report("LLM_MODE=remote: Ollama is not required")
        return 0

    host = config.ollama_host.rstrip("/")
    try:
        status, tags = _http_json(f"{host}/api/tags", timeout=5)
    except (urllib.error.URLError, OSError) as e:
        _report(
            f"Ollama is not reachable at {host}",
            [
                f"error: {_truncate(str(e))}",
                "hint: install Ollama from https://ollama.com/download and start it "
                "(desktop app or `ollama serve`), or point LLM_OLLAMA_HOST at your server.",
                OLLAMA_SKIP_HINT,
            ],
        )
        return 1
    if status != 200:
        _report(f"Ollama at {host} answered HTTP {status} on /api/tags", [OLLAMA_SKIP_HINT])
        return 1

    names = [str(m.get("name") or m.get("model") or "") for m in tags.get("models", [])]
    # Same rule as the API readiness probe: the configured name must be part of a pulled tag.
    if not any(config.model in name for name in names):
        _report(
            f"Ollama model {config.model} is not pulled",
            [
                f"available: {', '.join(names) if names else 'none'}",
                f"hint: ollama pull {config.model}   (or set LLM_LOCAL_MODEL to a pulled model)",
                OLLAMA_SKIP_HINT,
            ],
        )
        return 1

    started = time.perf_counter()
    try:
        status, body = _http_json(
            f"{host}/api/generate",
            payload={
                "model": config.model,
                "prompt": "Reply with the single word OK.",
                "stream": False,
                "options": {"num_predict": 1},
            },
            timeout=args.timeout,
        )
    except (urllib.error.URLError, OSError) as e:
        status, body = 0, {"error": str(e)}
    elapsed = time.perf_counter() - started

    if status != 200 or body.get("error"):
        _report(
            f"Ollama is running but cannot generate with {config.model}",
            [
                f"error: {_truncate(str(body.get('error') or f'HTTP {status}'))}",
                "hint: the server answers but cannot run the model. Reinstall or upgrade Ollama "
                "(https://ollama.com/download, or `brew reinstall ollama`), restart it, then retry.",
                OLLAMA_SKIP_HINT,
            ],
        )
        return 1

    _report(f"Ollama OK: {config.model} at {host} generated a token in {elapsed:.1f}s")
    return 0


# ---------------------------------------------------------------------------
# node
# ---------------------------------------------------------------------------

_VERSION_RE = re.compile(r"^v?(\d+|[xX*])(?:\.(\d+|[xX*]))?(?:\.(\d+|[xX*]))?")
_COMPARATOR_RE = re.compile(r"(\^|~|>=|<=|>|<|=)?\s*(v?[0-9xX*][0-9A-Za-z.*-]*)")


def _parse_version(text: str) -> tuple[int, int, int]:
    match = _VERSION_RE.match(text.strip())
    if not match:
        raise ValueError(f"not a version: {text!r}")
    parts = [int(p) if p and p.isdigit() else 0 for p in match.groups()]
    return parts[0], parts[1], parts[2]


def _partial_version(text: str) -> tuple[list[int], int]:
    """Parse '22', '22.13', '22.13.0', '22.x' into (padded parts, number of given parts)."""
    match = _VERSION_RE.match(text.strip())
    if not match:
        raise ValueError(f"not a version: {text!r}")
    given = [p for p in match.groups() if p is not None and p not in {"x", "X", "*"}]
    parts = [int(p) for p in given] + [0] * (3 - len(given))
    return parts, len(given)


def _comparator_bounds(operator: str, text: str) -> list[tuple[str, tuple[int, int, int]]]:
    """Translate one semver comparator into a list of (op, version) primitive bounds."""
    parts, given = _partial_version(text)
    base = (parts[0], parts[1], parts[2])
    if given == 0:
        return []  # '*' / 'x': any version
    if operator == "^":
        if parts[0] > 0 or given == 1:
            upper = (parts[0] + 1, 0, 0)
        elif parts[1] > 0 or given == 2:
            upper = (0, parts[1] + 1, 0)
        else:
            upper = (0, 0, parts[2] + 1)
        return [(">=", base), ("<", upper)]
    if operator == "~":
        upper = (parts[0] + 1, 0, 0) if given == 1 else (parts[0], parts[1] + 1, 0)
        return [(">=", base), ("<", upper)]
    if operator in {"", "="}:
        if given == 3:
            return [("=", base)]
        upper = (parts[0] + 1, 0, 0) if given == 1 else (parts[0], parts[1] + 1, 0)
        return [(">=", base), ("<", upper)]
    if operator == ">" and given < 3:
        upper = (parts[0] + 1, 0, 0) if given == 1 else (parts[0], parts[1] + 1, 0)
        return [(">=", upper)]
    if operator == "<=" and given < 3:
        upper = (parts[0] + 1, 0, 0) if given == 1 else (parts[0], parts[1] + 1, 0)
        return [("<", upper)]
    return [(operator, base)]


_BOUND_CHECKS = {
    ">=": lambda a, b: a >= b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    "<": lambda a, b: a < b,
    "=": lambda a, b: a == b,
}


def satisfies(version: str, version_range: str) -> bool:
    """Check a version against an npm-style range ('^22.13.0 || >=24', '>=20 <21', '22.x').

    Supports `||` alternatives and the ^ ~ >= > <= < = comparators (hyphen ranges are not used
    by this repo and are not supported).
    """
    current = _parse_version(version)
    for alternative in version_range.split("||"):
        alternative = alternative.strip()
        if not alternative or alternative == "*":
            return True
        bounds: list[tuple[str, tuple[int, int, int]]] = []
        for operator, text in _COMPARATOR_RE.findall(alternative):
            bounds.extend(_comparator_bounds(operator, text))
        if all(_BOUND_CHECKS[op](current, bound) for op, bound in bounds):
            return True
    return False


def _pinned_node_major() -> str | None:
    """The Node major version pinned in .node-version (``24`` for ``24`` or ``v24.1.0``)."""
    try:
        match = re.match(r"v?(\d+)", (PROJECT_ROOT / ".node-version").read_text(encoding="utf-8"))
    except OSError:
        return None
    return match.group(1) if match else None


def _node_switch_hint(reason: str) -> list[str]:
    """How to get the pinned Node with each version manager. nvm reads .nvmrc, not .node-version."""
    major = _pinned_node_major()
    version = f"Node {major}" if major else "the Node version in .node-version"
    return [
        f"hint: {reason} Get {version} from the repository root:",
        "`fnm use --install-if-missing` (reads .node-version), `nvm install` (reads .nvmrc),",
        f"`volta install node@{major or '<version>'}`, or the installer from https://nodejs.org.",
        "Or set SKIP_FRONTEND=1 to skip the frontend.",
    ]


def cmd_node(args: argparse.Namespace) -> int:
    package_json = PROJECT_ROOT / "frontend" / "package.json"
    try:
        engines = json.loads(package_json.read_text(encoding="utf-8")).get("engines", {})
    except (OSError, json.JSONDecodeError) as e:
        _report(f"Cannot read {package_json}: {e}")
        return 1
    required = str(engines.get("node") or "*")

    try:
        found = subprocess.run(
            ["node", "--version"], capture_output=True, text=True, check=True, timeout=15
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        _report(
            f"Node.js not found (frontend needs {required})",
            _node_switch_hint("The frontend needs Node.js."),
        )
        return 1

    try:
        compatible = satisfies(found, required)
    except ValueError as e:
        _report(f"Cannot compare Node {found} with engines.node {required!r}: {e}")
        return 1
    if not compatible:
        _report(
            f"Node {found} does not satisfy frontend engines.node {required!r}",
            _node_switch_hint("`npm ci` refuses to install with it (engine-strict)."),
        )
        return 1
    _report(f"Node {found} satisfies engines.node {required!r}")
    return 0


# ---------------------------------------------------------------------------
# spacy
# ---------------------------------------------------------------------------


def cmd_spacy(args: argparse.Namespace) -> int:
    try:
        import spacy.util
    except Exception as e:
        _report("spaCy is not importable (run `make install`)", [f"error: {_truncate(str(e))}"])
        return 1
    if not spacy.util.is_package(SPACY_MODEL):
        _report(
            f"spaCy model {SPACY_MODEL} is not installed (concept extraction degrades without it)",
            [f"hint: poetry run python -m spacy download {SPACY_MODEL}"],
        )
        return 1
    _report(f"spaCy model {SPACY_MODEL} is installed")
    return 0


# ---------------------------------------------------------------------------
# wait / seed-status (need the backend dependencies)
# ---------------------------------------------------------------------------


def _require_backend_settings() -> Any:
    settings = _backend_settings()
    if settings is None:
        raise SystemExit("Backend settings are not importable; run this with `poetry run python`.")
    return settings


def _opensearch_base(settings: Any) -> tuple[str, tuple[str, str] | None, ssl.SSLContext | None]:
    scheme = "https" if settings.opensearch_use_ssl else "http"
    base = f"{scheme}://{settings.opensearch_host}:{settings.opensearch_port}"
    auth = (
        (settings.opensearch_user, settings.opensearch_password)
        if settings.opensearch_password
        else None
    )
    context = None
    if settings.opensearch_use_ssl and not settings.opensearch_verify_certs:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return base, auth, context


def _check_neo4j(settings: Any) -> str | None:
    """Return None when Neo4j answers `RETURN 1` over bolt, else an error description."""
    from neo4j import GraphDatabase
    from neo4j.exceptions import AuthError

    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
        connection_timeout=5,
    )
    try:
        with driver.session(database=settings.neo4j_database) as session:
            session.run("RETURN 1").consume()
    except AuthError as e:
        raise SystemExit(
            f"Neo4j at {settings.neo4j_uri} rejected the credentials: {e}\n"
            "    hint: NEO4J_PASSWORD must match the password the Neo4j volume was created with "
            "(it is only applied on the first start of an empty volume)."
        ) from e
    except Exception as e:
        return _truncate(f"{type(e).__name__}: {e}", 200)
    finally:
        driver.close()
    return None


def _check_opensearch(settings: Any) -> str | None:
    """Return None when the OpenSearch cluster is at least yellow, else an error description."""
    base, auth, context = _opensearch_base(settings)
    url = f"{base}/_cluster/health?wait_for_status=yellow&timeout=5s"
    try:
        status, body = _http_json(url, timeout=10, auth=auth, context=context)
    except (urllib.error.URLError, OSError) as e:
        return _truncate(str(e), 200)
    if status == 200 and body.get("status") in {"yellow", "green"}:
        return None
    return f"HTTP {status}, cluster status {body.get('status', 'unknown')}"


def cmd_wait(args: argparse.Namespace) -> int:
    settings = _require_backend_settings()
    # The driver logs every refused connection; the summary below is enough.
    logging.getLogger("neo4j").setLevel(logging.CRITICAL)
    base, _, _ = _opensearch_base(settings)
    deadline = time.monotonic() + args.timeout
    next_report = 0.0
    while True:
        neo4j_error = _check_neo4j(settings)
        opensearch_error = _check_opensearch(settings)
        if neo4j_error is None and opensearch_error is None:
            _report(f"Neo4j ({settings.neo4j_uri}) and OpenSearch ({base}) are ready")
            return 0
        now = time.monotonic()
        if now >= deadline:
            details = []
            if neo4j_error:
                details.append(f"neo4j {settings.neo4j_uri}: {neo4j_error}")
            if opensearch_error:
                details.append(f"opensearch {base}: {opensearch_error}")
            details.append(
                "hint: `make up` starts both databases; `make doctor` shows ports and "
                "container health."
            )
            _report(f"Databases not ready after {args.timeout:.0f}s", details)
            return 1
        if args.verbose and now >= next_report:
            waiting = [
                name
                for name, err in (("neo4j", neo4j_error), ("opensearch", opensearch_error))
                if err
            ]
            print(f"  waiting for {', '.join(waiting)}...", flush=True)
            next_report = now + 10
        time.sleep(min(2.0, max(0.0, deadline - now)))


def cmd_seed_status(args: argparse.Namespace) -> int:
    settings = _require_backend_settings()
    from neo4j import GraphDatabase

    from backend.app.core.subjects import get_subject

    subject = get_subject(args.subject)
    label = f"{subject.database.label_prefix}_Concept"
    driver = GraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    try:
        with driver.session(database=subject.database.neo4j_database) as session:
            record = session.run(f"MATCH (c:`{label}`) RETURN count(c) AS n").single()
            concepts = int(record["n"]) if record else 0
    finally:
        driver.close()

    base, auth, context = _opensearch_base(settings)
    status, body = _http_json(
        f"{base}/{subject.database.opensearch_index}/_count", timeout=10, auth=auth, context=context
    )
    chunks = int(body.get("count", 0)) if status == 200 else 0
    print(f"{concepts} {chunks}")
    return 0


def _index_embedding_meta(
    settings: Any, index: str
) -> tuple[int, dict[str, Any] | None, str | None]:
    """(HTTP status, the index's ``_meta.embedding`` or None, error) for one index."""
    base, auth, context = _opensearch_base(settings)
    try:
        status, body = _http_json(
            f"{base}/{index}/_mapping", timeout=10, auth=auth, context=context
        )
    except (urllib.error.URLError, OSError) as e:
        return 0, None, _truncate(str(e))
    if status != 200:
        return status, None, None if status == 404 else f"HTTP {status}"
    # Keyed by the concrete index name, which differs from `index` when that is an alias
    entry = body.get(index) or (next(iter(body.values())) if len(body) == 1 else {})
    meta = (entry.get("mappings") or {}).get("_meta", {}).get("embedding")
    return status, meta if isinstance(meta, dict) else None, None


def cmd_index_fingerprint(args: argparse.Namespace) -> int:
    """Compare each seeded index's embedding fingerprint with the installed stack (#71)."""
    settings = _require_backend_settings()
    from backend.app.core.privacy import hf_model_is_cached
    from backend.app.core.subjects import get_subject

    errors: list[str] = []
    warnings: list[str] = []
    fingerprinted: list[tuple[str, str, dict[str, Any]]] = []
    for subject_id in args.subjects:
        index = get_subject(subject_id).database.opensearch_index
        status, meta, error = _index_embedding_meta(settings, index)
        if error:
            errors.append(f"{subject_id}: cannot read the {index} mapping ({error})")
        elif status == 404:
            continue  # not seeded; the seed check reports it
        elif meta is None:
            warnings.append(
                f"{subject_id}: {index} was built before index fingerprints; rebuild it to "
                f"enable this check (make index-rag SUBJECT={subject_id} RECREATE=1)"
            )
        else:
            fingerprinted.append((subject_id, index, meta))

    model_name, revision = settings.embedding_model, settings.effective_embedding_revision
    checked: list[str] = []
    mismatched = False
    lowest = 1.0
    if fingerprinted and not hf_model_is_cached(model_name, revision):
        warnings.append(
            f"{model_name} (revision {revision}) is not cached, so the fingerprints were not "
            "checked; it downloads on the API's first start"
        )
    elif fingerprinted:
        # Cached: never contact the Hub from here
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        from backend.app.nlp.embeddings import EmbeddingModel
        from backend.app.rag.index_fingerprint import check_fingerprint

        model = EmbeddingModel()
        try:
            model.load()
        except Exception as e:
            errors.append(f"{model_name} failed to load: {_truncate(f'{type(e).__name__}: {e}')}")
        else:
            for subject_id, index, meta in fingerprinted:
                check = check_fingerprint(meta, model)
                checked.append(subject_id)
                if check.probe_cosine is not None:
                    lowest = min(lowest, check.probe_cosine)
                errors.extend(f"{subject_id}: {problem}" for problem in check.errors)
                warnings.extend(f"{subject_id}: {problem}" for problem in check.warnings)
                if check.errors:
                    mismatched = True
                    errors.append(
                        f"hint: rebuild {index} with make index-rag SUBJECT={subject_id} "
                        "RECREATE=1 (and make build-windows if you use window retrieval)"
                    )

    if errors:
        summary = "do not match the embedding stack" if mismatched else "could not be checked"
        _report(f"Index fingerprints {summary}", [*errors, *warnings])
        return 1
    if warnings:
        _report(
            f"Index fingerprints: {len(warnings)} warning(s) "
            f"(checked: {', '.join(checked) or 'none'})",
            warnings,
        )
        return 2
    if not checked:
        _report("Index fingerprints: no seeded index to check")
        return 0
    _report(
        f"Index fingerprints match the embedding stack ({', '.join(checked)}; "
        f"lowest probe cosine {lowest:.6f})"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    sub = parser.add_subparsers(dest="command", required=True)

    ollama = sub.add_parser("ollama", help="Ollama reachable, model pulled, 1-token generation")
    ollama.add_argument("--timeout", type=float, default=120.0, help="generation timeout (s)")
    ollama.set_defaults(func=cmd_ollama)

    python_range = sub.add_parser("python-range", help="backend Python range from pyproject.toml")
    python_range.add_argument("--version", help="check an installed numeric Python version")
    python_range.set_defaults(func=cmd_python_range)

    node = sub.add_parser("node", help="node --version satisfies frontend engines.node")
    node.set_defaults(func=cmd_node)

    spacy_parser = sub.add_parser("spacy", help=f"spaCy model {SPACY_MODEL} is installed")
    spacy_parser.set_defaults(func=cmd_spacy)

    wait = sub.add_parser("wait", help="wait until Neo4j and OpenSearch accept requests")
    wait.add_argument("--timeout", type=float, default=180.0, help="seconds to wait")
    wait.add_argument("--verbose", action="store_true", help="print progress while waiting")
    wait.set_defaults(func=cmd_wait)

    status = sub.add_parser("seed-status", help='print "<concepts> <indexed chunks>"')
    status.add_argument("--subject", required=True)
    status.set_defaults(func=cmd_seed_status)

    fingerprint = sub.add_parser(
        "index-fingerprint", help="the indexes' embedding fingerprints match the installed stack"
    )
    fingerprint.add_argument("subjects", nargs="+", metavar="SUBJECT")
    fingerprint.set_defaults(func=cmd_index_fingerprint)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
