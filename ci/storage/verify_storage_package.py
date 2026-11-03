#!/usr/bin/env python3
"""Host-only final root/Data layout gate. Reads artifacts; prints JSON; never writes a device."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import tomllib
from support.packed_ramdisk import regions

FIRST, LAST, SECTOR = 173859584, 257745663, 4096
CAPACITY = 320 << 30
DATA_BYTES = 215 << 30
RESERVE_BLOCKS = 1024 * 256
GUARD_BLOCKS = 1024


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def geometry(root_bytes, data_bytes=DATA_BYTES):
    require(root_bytes > 0 and root_bytes % SECTOR == 0, "root image must be 4K aligned")
    require(data_bytes == DATA_BYTES, "Data logical capacity must remain 215 GiB")
    pages = data_bytes // SECTOR
    bitmap_blocks = (pages + 8 * SECTOR - 1) // (8 * SECTOR)
    store_blocks = 1 + bitmap_blocks + pages  # author seed-data-grow.py / RamBlock PersistentStore
    partition_blocks = LAST - FIRST + 1
    require(partition_blocks * SECTOR == CAPACITY, "proposal geometry inconsistent")
    root_blocks = root_bytes // SECTOR
    require(partition_blocks - store_blocks - RESERVE_BLOCKS >= root_blocks + GUARD_BLOCKS,
            "root + guard + Data store metadata + Data + log reserve exceed unixnu")
    data_first = LAST + 1 - RESERVE_BLOCKS - store_blocks
    return dict(partition_bytes=CAPACITY, root_bytes=root_bytes, data_logical_bytes=data_bytes,
                data_store_blocks=store_blocks, data_metadata_bytes=(1 + bitmap_blocks) * SECTOR,
                data_first_lba=data_first, data_last_lba=LAST - RESERVE_BLOCKS,
                root_end_lba=FIRST + root_blocks - 1, guard_blocks=GUARD_BLOCKS,
                log_reserve_blocks=RESERVE_BLOCKS,
                remaining_between_root_guard_and_data_bytes=
                (data_first - FIRST - root_blocks - GUARD_BLOCKS) * SECTOR)


def verify(board_path, root_path, report_path, seed_path):
    board = tomllib.loads(board_path.read_text())
    target = board["userdata"]
    require((target.get("partition_name"), target["first_lba"], target["last_lba"],
             target["lba_bytes"]) == ("unixnu", FIRST, LAST, SECTOR), "wrong root target/geometry")
    require(board["payload"]["runtime"]["data_gib"] == 215, "changed author Data default")
    require(board["payload"]["adt"]["owned_memory_size"] == "0x130000000", "changed 4.75 GiB memory")
    reserve_args = [a for a in board["payload"]["kernel_args"] if a.startswith("sheng-log-reserve=")]
    require(not reserve_args or reserve_args == ["sheng-log-reserve=1024"], "unexpected log reserve override")
    report = json.loads(report_path.read_text())
    require(report.get("target_partition") == "unixnu" and report["userdata_bytes"] == CAPACITY,
            "root report target/size mismatch")
    require("flash_command" not in report, "root report must not contain a device-write command")
    size = root_path.stat().st_size
    require(size == report["image_bytes"], "root file/report size mismatch")
    require(sha256(root_path) == report["image_sha256"], "root file/report SHA256 mismatch")
    with root_path.open("rb") as stream:
        header = stream.read(SECTOR)
    require(len(header) == SECTOR and header[:8] == b"SHNGROOT", "root manifest missing")
    require(hashlib.sha256(header[:4064]).digest() == header[4064:], "root manifest SHA256 mismatch")
    version, count, image_bytes = struct.unpack_from("<IIQ", header, 8)
    require(version == 2 and count == 4 and image_bytes == size, "expected two windows and two hash-table objects")
    names, spans, actual = set(), [], {}
    for i in range(count):
        name_raw, offset, length, block, flags, digest = struct.unpack_from("<32sQQII32s", header, 24 + 128 * i)
        name = name_raw.split(b"\0", 1)[0].decode("ascii")
        require(name not in names and name in {"OS", "SystemOS", "OS.vroot", "SystemOS.vroot"},
                "unexpected/duplicate root entry")
        names.add(name)
        is_object = name.endswith(".vroot")
        require((block, flags) == ((4096, 3) if is_object else (512, 1)), "wrong root entry attributes")
        require(offset >= SECTOR and offset % SECTOR == 0 and length > 0
                and offset + ((length + 4095) // 4096) * 4096 <= size, "root entry outside image")
        require(not is_object or length > 544, "hash-table object absent or only a signed header")
        spans.append((offset, offset + ((length + 4095) // 4096) * 4096))
        actual[name] = dict(offset=offset, size=length, sha256=digest.hex())
    require(all(a[1] <= b[0] for a, b in zip(sorted(spans), sorted(spans)[1:])), "root entries overlap")
    listed = {e["name"]: {k: e[k] for k in ("offset", "size", "sha256")}
              for e in report["windows"] + report["objects"]}
    require(listed == actual, "manifest and root report entries differ")
    blob = seed_path.read_bytes()
    logical, extents = regions(blob)
    require(extents, "empty packed Data seed")
    layout = geometry(size, logical)
    return dict(status="HOST_ARTIFACT_LAYOUT_PASS_NOT_DEVICE_AUTHORIZATION",
                geometry_status="PROPOSED_320GIB_NOT_LIVE_VERIFIED", target_partition="unixnu",
                layout=layout, root_sha256=report["image_sha256"],
                data_seed_sha256=hashlib.sha256(blob).hexdigest(),
                required_objects="OS.vroot and SystemOS.vroot are hash tables; original signed headers/anchor checked by build",
                device_verified=False, hardware_success=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("board", "root-image", "root-report", "data-seed"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.board, args.root_image, args.root_report, args.data_seed), indent=2))


if __name__ == "__main__":
    main()
