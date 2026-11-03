#!/usr/bin/env python3
"""Validate ComfyUI UI-format workflows in this directory."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _as_list(value):
    return value if isinstance(value, list) else []


def validate(path: Path) -> bool:
    data = json.loads(path.read_text())
    nodes = data.get("nodes") or []
    links = data.get("links") or []
    errors: list[str] = []

    node_by_id = {}
    for node in nodes:
        nid = node.get("id")
        if nid in node_by_id:
            errors.append(f"duplicate node id {nid}")
        node_by_id[nid] = node

    # Top-level link ids must be unique.
    top_links: dict[int, list] = {}
    for link in links:
        if not isinstance(link, list) or len(link) != 6:
            errors.append(f"malformed link row: {link!r}")
            continue
        link_id = link[0]
        if link_id in top_links:
            errors.append(f"duplicate link id {link_id} in links table")
        top_links[link_id] = link

    out_refs: dict[int, list[tuple[int, int]]] = {}
    in_refs: dict[int, list[tuple[int, int]]] = {}
    for nid, node in node_by_id.items():
        for slot, out in enumerate(_as_list(node.get("outputs"))):
            for link_id in _as_list(out.get("links")):
                out_refs.setdefault(link_id, []).append((nid, slot))
        for slot, inp in enumerate(_as_list(node.get("inputs"))):
            link_id = inp.get("link")
            if link_id is not None:
                in_refs.setdefault(link_id, []).append((nid, slot))

    all_ref_ids = set(out_refs) | set(in_refs)
    for link_id in all_ref_ids:
        if link_id not in top_links:
            errors.append(f"link id {link_id} is referenced by a node but missing from links table")
    for link_id in top_links:
        if link_id not in all_ref_ids:
            errors.append(f"link id {link_id} in links table is not referenced by any node")

    # Every link appears exactly twice: once as an output, once as an input.
    for link_id in sorted(set(top_links) | all_ref_ids):
        outs = out_refs.get(link_id, [])
        ins = in_refs.get(link_id, [])
        if len(outs) != 1 or len(ins) != 1:
            errors.append(
                f"link id {link_id} appears {len(outs)} time(s) in outputs and "
                f"{len(ins)} time(s) in inputs (expected 1 and 1)"
            )
            continue

        link = top_links[link_id]
        _, origin_id, origin_slot, target_id, target_slot, link_type = link
        if origin_id not in node_by_id:
            errors.append(f"link id {link_id} origin node {origin_id} does not exist")
            continue
        if target_id not in node_by_id:
            errors.append(f"link id {link_id} target node {target_id} does not exist")
            continue

        origin = node_by_id[origin_id]
        target = node_by_id[target_id]
        origin_outputs = _as_list(origin.get("outputs"))
        target_inputs = _as_list(target.get("inputs"))
        if origin_slot < 0 or origin_slot >= len(origin_outputs):
            errors.append(f"link id {link_id} origin slot {origin_slot} is out of range")
            continue
        if target_slot < 0 or target_slot >= len(target_inputs):
            errors.append(f"link id {link_id} target slot {target_slot} is out of range")
            continue

        out_type = origin_outputs[origin_slot].get("type")
        in_type = target_inputs[target_slot].get("type")
        if out_type != in_type:
            errors.append(
                f"link id {link_id} type mismatch: output {out_type!r} -> input {in_type!r}"
            )
        if link_type != out_type:
            errors.append(
                f"link id {link_id} table type {link_type!r} != output type {out_type!r}"
            )

    max_node_id = max(node_by_id, default=0)
    max_link_id = max(top_links, default=0)
    if data.get("last_node_id", -1) < max_node_id:
        errors.append(
            f"last_node_id {data.get('last_node_id')} < max node id {max_node_id}"
        )
    if data.get("last_link_id", -1) < max_link_id:
        errors.append(
            f"last_link_id {data.get('last_link_id')} < max link id {max_link_id}"
        )

    status = "PASS" if not errors else "FAIL"
    print(f"{path}: {len(nodes)} nodes, {len(links)} links: {status}")
    for error in errors:
        print(f"  - {error}")
    return not errors


def main() -> int:
    here = Path(__file__).resolve().parent
    paths = [Path(arg) for arg in sys.argv[1:]] or sorted(here.glob("*.ui.json"))
    if not paths:
        print("No UI workflow files found.")
        return 1
    ok = True
    for path in paths:
        ok = validate(path) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
