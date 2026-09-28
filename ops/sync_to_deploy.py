"""Copy what CS-platform owns into the deployment repo (joveo/coder-pets-tray). Issue #43.

CS-platform is the source of truth for the Ask Naren frontend and service (#42). The
deployment repo adds what only a deployment needs -- Dockerfiles, the metrics routes, the
applib middleware stub, a trimmed config loader, its own test suite -- and those it OWNS:
this script never writes them. Everything else under the synced roots is overwritten from
here.

    python ops/sync_to_deploy.py                      # dry run: print what would change
    python ops/sync_to_deploy.py --apply              # write it
    python ops/sync_to_deploy.py --apply --init       # first sync: no manifest exists yet

THE FAILURE THIS EXISTS TO PREVENT is silent: a hand copy that clobbers a deployment-only
fix, or a downstream edit that the next copy erases. So every file this writes is recorded
in a manifest in the deployment repo (hash of what was written). If a synced file has been
edited downstream since, the sync STOPS and names it -- port the edit upstream (or make the
file deployment-owned below) and run again.

Deletions follow the same rule: a downstream file under a mirrored root is removed only if
this script wrote it before and it no longer exists upstream (that is how an archived page
leaves the deployment). A downstream file it never wrote is reported, never touched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MANIFEST = ".sync-from-cs-platform.json"


@dataclass(frozen=True)
class Tree:
    """One upstream directory mapped onto one downstream directory.

    `mirror` roots are owned outright: files are added, updated, and (if previously synced)
    deleted. `update_only` roots were VENDORED downstream -- only the modules the serving path
    reaches were copied -- so only files that already exist downstream are refreshed, and
    nothing is added there.
    """
    src: str
    dst: str
    mirror: tuple[str, ...]
    update_only: tuple[str, ...] = ()
    owned_downstream: tuple[str, ...] = ()


TREES = (
    Tree(
        src="frontend",
        dst="coder-pets-tray-app",
        mirror=("src", "db", "scripts"),
        owned_downstream=(
            # The deployment's operational surface, which CS-platform has no counterpart for.
            "src/app/api/health/**",
            "src/app/api/metrics/**",
            "src/instrumentation.ts",
            "src/lib/metrics.ts",
        ),
    ),
    Tree(
        src="Brain",
        dst="ask-naren",
        mirror=("ask_naren",),
        update_only=("shared", "preprocessing", "layer_d", "tuning.yaml"),
        owned_downstream=(
            # Deliberately adapted for a container (see each file's header): the root-level
            # entry point, the trimmed two-variable config loader, packaging, and the tests.
            "serve_ask_naren.py",
            "config.py",
            "setup.py",
            "tests/**",
        ),
    ),
)

IGNORED_PARTS = {"__pycache__", "node_modules", ".next", ".pytest_cache", "coverage"}


def _norm_hash(data: bytes) -> str:
    """Hash with line endings normalised: the deployment repo checks out CRLF, this one LF,
    and a difference in line endings alone is not drift."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _matches(rel: str, patterns: tuple[str, ...]) -> bool:
    p = PurePosixPath(rel)
    return any(p.match(pat) or (pat.endswith("/**") and rel.startswith(pat[:-3] + "/")) for pat in patterns)


def _files(root: Path) -> dict[str, Path]:
    if root.is_file():
        return {root.name: root}
    out = {}
    if not root.exists():
        return out
    for f in root.rglob("*"):
        if f.is_file() and not (set(f.relative_to(root).parts) & IGNORED_PARTS):
            out[f.relative_to(root).as_posix()] = f
    return out


@dataclass
class Plan:
    write: list[tuple[str, Path, Path]]       # (manifest key, upstream file, downstream file)
    delete: list[tuple[str, Path]]
    drift: list[str]
    unknown: list[str]
    unchanged: int


def plan(upstream: Path, downstream: Path, manifest: dict[str, str], init: bool) -> Plan:
    p = Plan([], [], [], [], 0)
    for t in TREES:
        up_base, down_base = upstream / t.src, downstream / t.dst
        for root in t.mirror + t.update_only:
            is_mirror = root in t.mirror
            up = _files(up_base / root)
            down = _files(down_base / root)
            prefix = root if (up_base / root).is_dir() or (down_base / root).is_dir() else ""
            for rel, uf in sorted(up.items()):
                sub = f"{prefix}/{rel}" if prefix else rel
                if _matches(sub, t.owned_downstream):
                    continue
                df = down_base / sub
                if not is_mirror and not df.exists():
                    continue  # vendored tree: never add modules the serving path did not need
                key = f"{t.dst}/{sub}"
                up_hash = _norm_hash(uf.read_bytes())
                if df.exists():
                    down_hash = _norm_hash(df.read_bytes())
                    if down_hash == up_hash:
                        p.unchanged += 1
                        continue
                    recorded = manifest.get(key)
                    if recorded is None and not init:
                        p.drift.append(f"{key}  (differs, and was never synced -- first run needs --init)")
                        continue
                    if recorded is not None and recorded != down_hash:
                        p.drift.append(f"{key}  (edited downstream since the last sync)")
                        continue
                p.write.append((key, uf, df))
            if is_mirror:
                for rel, df in sorted(down.items()):
                    sub = f"{prefix}/{rel}" if prefix else rel
                    if rel in up or _matches(sub, t.owned_downstream):
                        continue
                    key = f"{t.dst}/{sub}"
                    if key in manifest:
                        if manifest[key] != _norm_hash(df.read_bytes()):
                            p.drift.append(f"{key}  (removed upstream, but edited downstream)")
                        else:
                            p.delete.append((key, df))
                    elif init:
                        # The first sync takes ownership of the mirrored roots: whatever the
                        # hand copy left there that no longer exists upstream goes.
                        p.delete.append((key, df))
                    else:
                        p.unknown.append(key)
    return p


def apply(p: Plan, upstream: Path, downstream: Path, manifest_files: dict[str, str]) -> dict[str, str]:
    """Write and delete what `p` says; return the new manifest's file map. The map also
    records files that were already identical, so a later edit to them is caught as drift."""
    files = dict(manifest_files)
    for key, uf, df in p.write:
        df.parent.mkdir(parents=True, exist_ok=True)
        data = uf.read_bytes()
        df.write_bytes(data)
        files[key] = _norm_hash(data)
    for key, df in p.delete:
        df.unlink()
        files.pop(key, None)
    for t in TREES:
        for root in t.mirror + t.update_only:
            for rel, uf in _files(upstream / t.src / root).items():
                prefix = root if (upstream / t.src / root).is_dir() else ""
                sub = f"{prefix}/{rel}" if prefix else rel
                df = downstream / t.dst / sub
                if df.exists() and not _matches(sub, t.owned_downstream) and                         _norm_hash(df.read_bytes()) == _norm_hash(uf.read_bytes()):
                    files[f"{t.dst}/{sub}"] = _norm_hash(uf.read_bytes())
    return files


def _git_head(repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()


def _git_dirty(repo: Path, paths: list[str]) -> list[str]:
    out = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--", *paths],
                         capture_output=True, text=True, check=True).stdout
    return [l for l in out.splitlines() if l.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--deploy", type=Path, default=Path(__file__).resolve().parents[2] / "coder-pets-tray",
                    help="path to the joveo/coder-pets-tray checkout")
    ap.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    ap.add_argument("--init", action="store_true", help="first sync: accept differing files without a manifest")
    ap.add_argument("--allow-dirty", action="store_true", help="sync from uncommitted upstream files")
    args = ap.parse_args(argv)

    upstream = Path(__file__).resolve().parents[1]
    downstream = args.deploy.resolve()
    if not (downstream / "coder-pets-tray-app").is_dir():
        print(f"error: {downstream} does not look like a coder-pets-tray checkout", file=sys.stderr)
        return 2

    dirty = _git_dirty(upstream, [f"{t.src}/{r}" for t in TREES for r in t.mirror + t.update_only])
    if dirty and not args.allow_dirty:
        print("error: uncommitted changes under synced paths -- the manifest records a commit, so "
              "commit first (or pass --allow-dirty):\n  " + "\n  ".join(dirty), file=sys.stderr)
        return 2

    mpath = downstream / MANIFEST
    manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {"files": {}}
    if not mpath.exists() and not args.init:
        print("error: no manifest in the deployment repo; the first sync needs --init", file=sys.stderr)
        return 2

    p = plan(upstream, downstream, manifest["files"], args.init)
    for key, _, df in p.write:
        print(("  update " if df.exists() else "  add    ") + key)
    for key, _ in p.delete:
        print("  delete " + key)
    for u in p.unknown:
        print("  ?      " + u + "  (downstream only, never synced -- left alone)")
    print(f"{len(p.write)} to write, {len(p.delete)} to delete, {p.unchanged} unchanged, "
          f"{len(p.unknown)} unknown, {len(p.drift)} drifted")
    if p.drift:
        print("\nSTOPPED -- these would overwrite downstream edits:\n  " + "\n  ".join(p.drift), file=sys.stderr)
        return 1
    if not args.apply:
        print("(dry run -- pass --apply to write)")
        return 0

    files = apply(p, upstream, downstream, manifest["files"])
    mpath.write_text(json.dumps({"source": "harshilbhanushali-rgb/Agentic-Learning",
                                 "source_commit": _git_head(upstream),
                                 "files": dict(sorted(files.items()))}, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {mpath.name} (source commit {_git_head(upstream)[:7]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
