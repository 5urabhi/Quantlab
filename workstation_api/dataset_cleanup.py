"""One-confirmation, recoverable deletion of an uploaded dataset and ALL saved work.

Build the full, read-only reverse reference graph *before* permitting a
destructive action. Linked derived datasets, model/experiment results,
notebooks, reports, charts, projects and other saved records belong in the
same explicit preview. There is no silent data loss, manual cleanup loop,
permanent purge, or deletion of canonical shared Dhan market history.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path
import json
import re
import sqlite3

from . import model_lab, research_library as library, service

MAX_CASCADE_ITEMS = 1000
MAX_SCAN_ROWS = 20000
MAX_METADATA_BYTES = 12_000_000


def _read_metadata(path: Path) -> dict:
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise ValueError("Unsafe source metadata path: " + path.name)
    if path.stat().st_size > MAX_METADATA_BYTES:
        raise ValueError("Source metadata too large to review safely: " + path.name)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("Unreadable saved source metadata: " + path.name) from exc
    if not isinstance(value, dict):
        raise ValueError("Unexpected saved source metadata: " + path.name)
    return value


def _record_refs(payload: str, selected_ids: set[str]) -> bool:
    # Treat free-text mentions as references too, exactly as the existing
    # resource dependency guard does. Preview lists the matched saved item.
    return any(identifier in payload for identifier in selected_ids)


def _index_sources() -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Read every active saved resource, never a UI-paginated first page."""
    datasets: list[dict] = []
    for row in service.datasets(include_archived=True):
        dataset_id = row["id"]
        if library.resource_status("dataset", dataset_id)["trashed"]:
            continue
        folder, _ = service.dataset_path(dataset_id)
        linked = set()
        for filename, keys in (
            ("workstation_source.json", ("parent_dataset_id", "source_dataset_id")),
            ("RETURN_METHODOLOGY.json", ("source_dataset_id",)),
        ):
            meta = _read_metadata(folder / filename)
            linked.update(meta[k] for k in keys if isinstance(meta.get(k), str))
        datasets.append({"kind": "dataset", "id": dataset_id,
                         "title": row["label"], "parents": linked})

    models: list[dict] = []
    root = model_lab._run_root()
    if root.is_dir() and not root.is_symlink():
        for f in root.glob("*.json"):
            if f.is_symlink() or not model_lab.RUN_ID.fullmatch(f.stem):
                continue
            meta = _read_metadata(f)
            if not meta:
                continue
            source = meta.get("source") if isinstance(meta.get("source"), dict) else {}
            links = {val for val in (
                source.get("dataset_id"), meta.get("dataset_id"),
                meta.get("duplicated_from"), source.get("source_run_id"),
            ) if isinstance(val, str)}
            models.append({"kind": "model_run", "id": f.stem,
                           "title": str(meta.get("title") or f.stem)[:130],
                           "parents": links})

    runs: list[dict] = []
    if service.RESULTS.is_dir() and not service.RESULTS.is_symlink():
        for folder in service.RESULTS.iterdir():
            if not folder.is_dir() or folder.is_symlink() or not library.RUN_ID.fullmatch(folder.name):
                continue
            manifest = folder / "workstation_run.json"
            if not manifest.is_file():
                manifest = folder / "research_manifest.json"
            if not manifest.is_file():
                continue
            meta = _read_metadata(manifest)
            config = meta.get("config") if isinstance(meta.get("config"), dict) else {}
            source = meta.get("source") if isinstance(meta.get("source"), dict) else {}
            links = {val for val in (
                meta.get("dataset_id"), config.get("dataset_id"),
                source.get("dataset_id"), meta.get("parent_run_id"),
                meta.get("source_run_id"),
            ) if isinstance(val, str)}
            runs.append({"kind": "research_run", "id": folder.name,
                         "title": str(meta.get("name") or folder.name)[:130],
                         "parents": links})

    with library._connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id,kind,title,payload,updated_utc FROM records "
            "WHERE trashed=0 ORDER BY id LIMIT ?", (MAX_SCAN_ROWS + 1,),
        ).fetchall()
    if len(rows) > MAX_SCAN_ROWS:
        raise ValueError("Too many saved records to verify safely for deletion")
    records = [{"kind": row["kind"], "id": row["id"], "title": row["title"],
                "payload": row["payload"], "updated_utc": row["updated_utc"]}
               for row in rows]
    return datasets, models, runs, records


def _preflight(kind: str, item_id: str) -> tuple[Path | None, dict]:
    """Validate location, type and the resource's current on-disk identity."""
    if kind in library.KINDS:
        row = library.get(item_id)
        if row["trashed"]:
            raise ValueError("Saved item already in Trash: " + item_id)
        return None, {"updated_utc": row["updated_utc"]}
    path = library._resource_path(kind, item_id)
    if path.parent.is_symlink():
        raise ValueError("Unsafe saved-resource parent directory")
    stat = path.stat()
    return path, {"path": str(path), "modified_ns": stat.st_mtime_ns,
                  "size": stat.st_size}


def plan(dataset_id: str) -> dict:
    """Return all items that a single confirmation will move to Trash."""
    library._resource_key("dataset", dataset_id)
    root_path = library._resource_path("dataset", dataset_id)
    if library.resource_status("dataset", dataset_id)["trashed"]:
        raise ValueError("Dataset already in recoverable Trash")
    sources, models, runs, records = _index_sources()

    selected: dict[tuple[str, str], dict] = {}
    depths = {dataset_id: 0}
    parents = {dataset_id}
    reasons: dict[tuple[str, str], str] = {}
    # Descendant datasets are included before their upstream originals.
    # A saved TRI child is user data, so the consent dialog must include it.
    for _ in range(MAX_CASCADE_ITEMS + 1):
        changed = False
        for source in sources:
            if source["id"] in depths:
                continue
            linked_parents = source["parents"] & parents
            if linked_parents:
                depths[source["id"]] = 1 + max(depths[p] for p in linked_parents)
                parents.add(source["id"])
                selected[("dataset", source["id"])] = source
                reasons[("dataset", source["id"])] = "Derived version of selected data"
                changed = True

        known = parents | {item_id for (_, item_id) in selected}
        for item in models + runs:
            key = (item["kind"], item["id"])
            if key not in selected and item["parents"] & known:
                selected[key] = item
                reasons[key] = "Saved model or experiment using the selected data"
                changed = True

        known = parents | {item_id for (_, item_id) in selected}
        for item in records:
            key = (item["kind"], item["id"])
            if key not in selected and _record_refs(item["payload"], known):
                selected[key] = item
                reasons[key] = "Saved work referencing this dataset or another affected item"
                changed = True
        if len(selected) > MAX_CASCADE_ITEMS:
            raise ValueError("More than 1000 linked items; review the dataset archive instead")
        if not changed:
            break
    else:
        raise ValueError("Saved dependencies changed too often to review safely")

    root_entry = next((item for item in sources if item["id"] == dataset_id), None)
    if root_entry is None:
        raise ValueError("Dataset is unavailable")
    selected[("dataset", dataset_id)] = root_entry
    reasons[("dataset", dataset_id)] = "Selected dataset"

    # Every source must pass the same existing ownership/path protection gate.
    blockers: list[dict] = []
    fingerprint = []
    for kind, item_id in sorted(selected):
        item = selected[(kind, item_id)]
        try:
            _, stat = _preflight(kind, item_id)
            fingerprint.append({"kind": kind, "id": item_id, **stat})
        except (ValueError, OSError, FileNotFoundError) as exc:
            blockers.append({"kind": kind, "id": item_id,
                             "title": item["title"], "reason": str(exc)})
    # The preview itself must never move data or mark a reference as verified.
    token = sha256(json.dumps(
        {"dataset": dataset_id, "fingerprints": fingerprint,
         "blockers": blockers},
        sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()

    ordered = sorted(
        [entry for key, entry in selected.items() if key != ("dataset", dataset_id)],
        key=lambda item: (item["kind"], item["title"], item["id"]),
    )
    dependent_items = [{
        "kind": item["kind"], "id": item["id"], "title": item["title"],
        "reason": reasons[(item["kind"], item["id"])],
    } for item in ordered]
    counts = dict(Counter(x["kind"] for x in dependent_items))
    saved_runs = [x for x in dependent_items if x["kind"] in ("model_run", "research_run")]
    return {
        "dataset_id": dataset_id, "preview_token": token,
        "can_archive": True, "can_delete_all": not blockers,
        "can_trash_with_saved_runs": not blockers,  # legacy caller compatibility
        "dependent_items": dependent_items, "dependent_count": len(dependent_items),
        "dependent_run_count": len(saved_runs), "dependent_runs": saved_runs,
        "blocking_references": blockers, "counts": counts,
        "recoverable": True, "raw_market_data_preserved": True,
        "summary": ("Delete this dataset and all " + str(len(dependent_items)) +
                    " saved items listed below in one action. Everything moves "
                    "to recoverable Trash; shared original Dhan history stays intact."
                    if not blockers else
                    "Some files cannot safely be moved. Archive the dataset or "
                    "repair the identified unsafe source before deleting."),
    }


def delete(dataset_id: str, *, preview_token: str, confirm: bool = False) -> dict:
    """Only move items named in the unchanged preview. Roll back on any error."""
    if not confirm or not isinstance(preview_token, str) or not re.fullmatch(
            r"[0-9a-f]{64}", preview_token):
        raise ValueError("Review the complete deletion list and press Yes to confirm")
    with library.LOCK:
        review = plan(dataset_id)
        if not review["can_delete_all"]:
            raise ValueError("A protected or unreadable source prevents complete deletion")
        if review["preview_token"] != preview_token:
            raise ValueError("Saved work changed since the popup opened. "
                             "Review the updated deletion list and confirm again.")

        deps = review["dependent_items"]
        records = [x for x in deps if x["kind"] in library.KINDS]
        runs = [x for x in deps if x["kind"] in {"model_run", "research_run"}]
        dataset_depths: dict[str, int] = {dataset_id: 0}
        # Plan already discovers all linked versions. The rest of the order
        # matters only for dataset->child source links, which may be nested.
        for x in deps:
            if x["kind"] == "dataset":
                dataset_depths[x["id"]] = 1
        for _ in range(len(dataset_depths)):
            changed = False
            for child in list(dataset_depths):
                if child == dataset_id:
                    continue
                folder, _ = service.dataset_path(child)
                info = _read_metadata(folder / "workstation_source.json")
                parent = info.get("parent_dataset_id")
                if parent in dataset_depths and dataset_depths[child] <= dataset_depths[parent]:
                    dataset_depths[child] = dataset_depths[parent] + 1
                    changed = True
            if not changed:
                break
        datasets = sorted(dataset_depths, key=lambda name: (-dataset_depths[name], name))
        moved: list[tuple[str, str]] = []
        try:
            # Records stop blocking runs; runs stop blocking datasets. Move
            # all child versions before the source dataset itself.
            for item in records:
                library.action(item["id"], "trash")
                moved.append((item["kind"], item["id"]))
            for item in runs:
                library.resource_action(item["kind"], item["id"], "trash", confirm=True)
                moved.append((item["kind"], item["id"]))
            for item_id in datasets:
                library.resource_action("dataset", item_id, "trash", confirm=True)
                moved.append(("dataset", item_id))
        except Exception as exc:
            failed_restorations = []
            for kind, item_id in reversed(moved):
                try:
                    if kind in library.KINDS:
                        library.action(item_id, "restore")
                    else:
                        library.resource_action(kind, item_id, "restore")
                except Exception as restore_exc:
                    failed_restorations.append(kind + ":" + item_id + " (" +
                                               str(restore_exc) + ")")
            if failed_restorations:
                raise ValueError("Deletion interrupted; manual restoration required for: "
                                 + ", ".join(failed_restorations)) from exc
            raise ValueError("Deletion cancelled and all previously moved items restored: "
                             + str(exc)) from exc

    return {"status": "moved_to_recoverable_trash", "dataset_id": dataset_id,
            "deleted_count": len(moved), "dependent_count": len(deps),
            "dependent_run_count": len(runs),
            "deleted_items": [{"kind": kind, "id": item_id} for kind, item_id in moved],
            "shared_original_market_data_preserved": True,
            "permanently_purged": False}
