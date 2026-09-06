"""Private JSON/text checkpoints. Runtime defaults to off; replay requires writes.

Checksums detect corruption, not malicious replacement of a private manifest.
No credentials, headers, raw SDK objects, or pickle are accepted by this API.
"""
import ast
import contextlib
import contextvars
import copy
import hashlib
import logging
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

from stage_d_projection import PROJECTION_VERSION, canonical_json, digest, strict_json

REPOSITORY = Path(__file__).resolve().parent
CHECKPOINT_VERSION = "stage-d-checkpoint/1"
_active = contextvars.ContextVar("stage_d_checkpoint", default=None)
logger = logging.getLogger(__name__)


class CheckpointError(RuntimeError):
    pass


def source_manifest(package_files):
    return [{"name": name, "sha256": hashlib.sha256(content).hexdigest()}
            for name, content in package_files]


def runtime_versions():
    """D-only changes can reuse A/B/C; upstream code and prompt must match."""
    source = (REPOSITORY / "extractor.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    chunks = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_REQUIREMENT_FIELDS" for t in node.targets):
            break
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and ("STAGE_D" in t.id or t.id == "LEGACY_STAGE_D_SYNTHESIS_PROMPT") for t in node.targets):
            continue
        if isinstance(node, (ast.FunctionDef, ast.Assign)):
            chunks.append(ast.dump(node, include_attributes=False))
    for filename in ("requirement_semantics.py", "evaluation_hierarchy.py"):
        chunks.append((REPOSITORY / filename).read_text(encoding="utf-8"))
    import extractor
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPOSITORY,
                                      text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        sha = "unavailable"
    return {"code_sha": sha, "upstream_code_digest": digest(chunks),
            "stage_a_prompt_digest": digest(extractor.STAGE_A_FACT_EXTRACTION_PROMPT),
            "stage_d_prompt_digest": digest(extractor.STAGE_D_SYNTHESIS_PROMPT),
            "stage_d_code_digest": digest((REPOSITORY / "stage_d_projection.py").read_text(encoding="utf-8")),
            "projection_version": PROJECTION_VERSION, "model": "claude-haiku-4-5-20251001"}


def _outside_repository(path):
    resolved = Path(path).expanduser().resolve()
    if resolved == REPOSITORY or REPOSITORY in resolved.parents:
        raise CheckpointError("Checkpoint root must be outside the repository")
    if any((p / ".git").exists() for p in (resolved, *resolved.parents)):
        raise CheckpointError("Checkpoint root must be outside any Git checkout")
    return resolved


def _artifact_path(root, name):
    path = (root / name).resolve()
    if path == root or root not in path.parents or Path(name).is_absolute():
        raise CheckpointError("Invalid checkpoint artifact path")
    return path


def _atomic_write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".checkpoint-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class CheckpointStore:
    """A per-run manifest and atomic writer; failures obey the configured mode."""

    def __init__(self, package_files=None, *, mode=None, root=None, versions=None):
        self.mode = mode if mode is not None else os.getenv("CHECKPOINT_MODE", "off")
        if self.mode not in {"off", "best_effort", "required"}:
            raise CheckpointError("CHECKPOINT_MODE must be off, best_effort, or required")
        self.errors = []
        self.root = None
        self.manifest = None
        if self.mode == "off":
            return
        try:
            configured = root if root is not None else os.getenv("CHECKPOINT_ROOT")
            if not configured:
                raise CheckpointError("CHECKPOINT_ROOT is not configured")
            base = _outside_repository(configured)
            sources = source_manifest(package_files or [])
            self.root = base / "stage-d" / digest(sources) / uuid.uuid4().hex
            self.manifest = {"checkpoint_version": CHECKPOINT_VERSION,
                             "source_scope": "package" if package_files is not None else "normalized-only",
                             "sources": sources, "package_digest": digest(sources),
                             "versions": versions if versions is not None else runtime_versions(),
                             "artifacts": {}, "errors": []}
            _atomic_write(self.root / "manifest.json", canonical_json(self.manifest).encode("utf-8"))
        except (OSError, RuntimeError, ValueError) as exc:
            self._failure("manifest.json", exc)

    def _failure(self, artifact, exc):
        # Never log exception strings: provider errors and paths may contain data.
        error = {"artifact": artifact, "error_type": type(exc).__name__}
        self.errors.append(error)
        logger.warning("Checkpoint persistence failed (%s): %s", self.mode, error)
        if self.mode == "required":
            raise CheckpointError(f"Required checkpoint failed: {artifact}") from exc

    def write(self, name, value, *, text=False):
        if self.mode == "off":
            return
        try:
            if self.root is None or self.manifest is None:
                raise CheckpointError("Checkpoint initialization failed")
            raw = (value if text else canonical_json(value)).encode("utf-8")
            path = _artifact_path(self.root, name)
            _atomic_write(path, raw)
            manifest = copy.deepcopy(self.manifest)
            manifest["artifacts"][name] = {"sha256": hashlib.sha256(raw).hexdigest(),
                                            "bytes": len(raw), "format": "text" if text else "json"}
            manifest["errors"] = list(self.errors)
            _atomic_write(self.root / "manifest.json", canonical_json(manifest).encode("utf-8"))
            self.manifest = manifest
        except (OSError, RuntimeError, ValueError) as exc:
            self._failure(name, exc)


def current_checkpoint():
    return _active.get()


@contextlib.contextmanager
def checkpoint_run(package_files=None, **options):
    existing = current_checkpoint()
    if existing is not None:
        if options:
            raise CheckpointError("Explicit checkpoint configuration cannot inherit another run")
        yield existing
        return
    store = CheckpointStore(package_files, **options)
    token = _active.set(store)
    try:
        yield store
    finally:
        _active.reset(token)


def pack_preprocessed(value):
    """Explicit JSON codec preserves preprocessing tuple/set/integer-key types."""
    if isinstance(value, dict):
        return {"type": "dict", "items": [[pack_preprocessed(k), pack_preprocessed(v)] for k, v in value.items()]}
    if isinstance(value, (list, tuple, set)):
        items = sorted(value) if isinstance(value, set) else value
        return {"type": type(value).__name__, "items": [pack_preprocessed(v) for v in items]}
    canonical_json(value)
    return {"type": "scalar", "value": value}


def unpack_preprocessed(value):
    if value["type"] == "scalar":
        return value["value"]
    if value["type"] == "dict":
        return {unpack_preprocessed(k): unpack_preprocessed(v) for k, v in value["items"]}
    constructors = {"list": list, "tuple": tuple, "set": set}
    if value["type"] not in constructors:
        raise CheckpointError("Unknown preprocessing codec type")
    return constructors[value["type"]](unpack_preprocessed(v) for v in value["items"])


def load_verified_checkpoint(run_directory, package_files, *, versions=None):
    """Read verified A/B/C artifacts. Never reuse D artifacts, even same version.

    Actual source bytes are required; caller-provided filenames alone do not
    establish source identity. Code SHA is recorded, upstream digests enforce
    compatibility across commits that change only Stage D.
    """
    root = _outside_repository(run_directory)
    try:
        manifest = strict_json((root / "manifest.json").read_text(encoding="utf-8"))
        if manifest["checkpoint_version"] != CHECKPOINT_VERSION or manifest["source_scope"] != "package":
            raise CheckpointError("Unsupported checkpoint version or source scope")
        actual = source_manifest(package_files)
        if manifest["sources"] != actual or manifest["package_digest"] != digest(actual):
            raise CheckpointError("Checkpoint source hashes do not match")
        current = versions if versions is not None else runtime_versions()
        previous = manifest["versions"]
        if previous.keys() != current.keys():
            raise CheckpointError("Checkpoint version manifest is incomplete")
        for field in ("upstream_code_digest", "stage_a_prompt_digest", "model"):
            if previous[field] != current[field]:
                raise CheckpointError(f"Stale checkpoint: {field}")
        artifacts = {}
        # Validate every manifested checksum, including rejected D evidence.
        for name, info in manifest["artifacts"].items():
            path = _artifact_path(root, name)
            raw = path.read_bytes()
            if len(raw) != info["bytes"] or hashlib.sha256(raw).hexdigest() != info["sha256"]:
                raise CheckpointError(f"Checkpoint checksum mismatch: {name}")
            if info["format"] not in {"json", "text"}:
                raise CheckpointError("Invalid checkpoint artifact format")
            if name.startswith(("stage-a/", "stage-b/", "stage-c/")) or name == "preprocessed-inputs.json":
                if info["format"] != "json":
                    raise CheckpointError("Upstream checkpoints must be JSON")
                artifacts[name] = strict_json(raw.decode("utf-8"))
        return {"manifest": manifest, "artifacts": artifacts,
                "stage_d_rebuild_required": True,
                "code_sha_changed": previous["code_sha"] != current["code_sha"],
                "stage_d_version_changed": any(previous[k] != current[k] for k in ("projection_version", "stage_d_prompt_digest", "stage_d_code_digest"))}
    except (OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
        if isinstance(exc, CheckpointError):
            raise
        raise CheckpointError("Invalid or incomplete checkpoint bundle") from exc


def resume_procurement_checkpoint(run_directory, package_files, api_key, *, checkpoint_root=None):
    """Resume verified A/B/C work; B+C present means zero Stage A API calls.

    Replays always write a new required bundle. Missing document checkpoints
    may be extracted from verified preprocessing, without redoing saved A work.
    """
    import extractor
    verified = load_verified_checkpoint(run_directory, package_files)
    artifacts = verified["artifacts"]
    with checkpoint_run(package_files, mode="required", root=checkpoint_root) as checkpoint:
        checkpoint.write("resume-origin.json", {"manifest_digest": digest(verified["manifest"]),
                                                "code_sha_changed": verified["code_sha_changed"],
                                                "stage_d_version_changed": verified["stage_d_version_changed"]})
        for name, value in artifacts.items():
            checkpoint.write(name, value)
        normalized = artifacts.get("stage-b/normalized-facts.json")
        if normalized is None:
            packed = artifacts.get("preprocessed-inputs.json")
            if packed is None:
                raise CheckpointError("Cannot resume Stage B without preprocessing metadata")
            metadata = unpack_preprocessed(packed)
            if metadata["files"] != [name for name, _ in package_files]:
                raise CheckpointError("Preprocessed file order does not match sources")
            document_facts = artifacts.get("stage-a/document-facts.json")
            if document_facts is None:
                document_facts = []
                for index, (name, _) in enumerate(package_files, 1):
                    artifact = f"stage-a/document-{index:04d}.json"
                    facts = artifacts.get(artifact)
                    if facts is None:
                        facts = extractor.extract_document_facts(metadata["doc_texts"][name], name, api_key)
                        checkpoint.write(artifact, facts)
                    document_facts.append(facts)
                checkpoint.write("stage-a/document-facts.json", document_facts)
            if not isinstance(document_facts, list) or len(document_facts) != len(package_files):
                raise CheckpointError("Stage A document coverage mismatch")
            normalized = extractor.normalize_package_facts(document_facts, metadata)
            checkpoint.write("stage-b/normalized-facts.json", normalized)
        conflicts = artifacts.get("stage-c/conflicts.json")
        if conflicts is None:
            conflicts = extractor.reconcile_package_facts(normalized, [name for name, _ in package_files])
            checkpoint.write("stage-c/conflicts.json", conflicts)
        synthesis = extractor.synthesize_bid_brief(normalized, conflicts, api_key)
        result = extractor._assemble_procurement_result(synthesis, normalized, conflicts)
        checkpoint.write("stage-d/final-result.json", result)
        return result, "claude-haiku-4-5-20251001 (Staged Pipeline A->B->C->D)"
