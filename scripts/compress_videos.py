"""Organize + compress repo media so everything fits GitHub's 100MB/file limit.

Usage:
  python scripts/compress_videos.py --organize-only   # move photos/docs/small videos, list big ones
  python scripts/compress_videos.py --all             # organize + compress big videos + stash originals
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[1]
PHOTOS = ROOT / "assets" / "photos"
VIDEOS = ROOT / "assets" / "videos"
BACKUP = ROOT / "assets" / "videos_originals_backup"
DOCS = ROOT / "docs"
LIMIT = 95 * 1024 * 1024  # stay safely under GitHub's 100MB hard limit
TARGET_MB = 90

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

PHOTO_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
DOC_EXTS = {".pdf", ".pptx", ".docx", ".xlsx", ".csv"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi"}
SKIP_DIRS = {".git", "assets", "docs", "scripts"}


def iter_media():
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts[:-1]):
            continue
        yield p


def safe_move(src: Path, dest_dir: Path):
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    i = 2
    while dest.exists():
        dest = dest_dir / f"{src.stem}_{i}{src.suffix}"
        i += 1
    shutil.move(str(src), str(dest))
    return dest


def duration_sec(p: Path):
    r = subprocess.run([FFMPEG, "-i", str(p)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    if not m:
        raise RuntimeError(f"no duration for {p.name}: {r.stderr[-500:]}")
    h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mi * 60 + s


def compress(src: Path, target_mb: int = TARGET_MB):
    dur = duration_sec(src)
    audio_kbps = 96
    v_kbps = int((target_mb * 1024 * 1024 * 8 / dur - audio_kbps * 1000) / 1000)
    width = 1280
    if v_kbps < 600:
        width = 854  # tiny bitrate budget -> smaller frame compresses cleaner
    v_kbps = max(v_kbps, 150)
    VIDEOS.mkdir(parents=True, exist_ok=True)
    out = VIDEOS / (src.stem + ".mp4")
    i = 2
    while out.exists():
        out = VIDEOS / f"{src.stem}_{i}.mp4"
        i += 1
    cmd = [FFMPEG, "-y", "-i", str(src),
           "-vf", f"scale={width}:-2,fps=30",
           "-c:v", "libx264", "-preset", "veryfast",
           "-b:v", f"{v_kbps}k", "-maxrate", f"{v_kbps * 2}k",
           "-bufsize", f"{v_kbps * 2}k",
           "-c:a", "aac", "-b:a", f"{audio_kbps}k", "-ac", "2",
           "-movflags", "+faststart", str(out)]
    print(f"[compress] {src.name} ({dur / 60:.1f} min) -> {out.name} @ {v_kbps}k {width}px",
          flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-2000:])
    size = out.stat().st_size
    print(f"  done: {size / 1024 / 1024:.1f} MB", flush=True)
    if size > LIMIT and target_mb > 60:
        print("  over limit, retrying smaller...", flush=True)
        out.unlink()
        return compress(src, target_mb - 10)
    if size > LIMIT:
        raise RuntimeError(f"still over limit: {src.name}")
    return out


def organize():
    big = []
    for p in list(iter_media()):
        ext = p.suffix.lower()
        if ext in PHOTO_EXTS:
            d = safe_move(p, PHOTOS)
            print(f"[photo] {p.name} -> {d.relative_to(ROOT)}")
        elif ext in DOC_EXTS:
            d = safe_move(p, DOCS)
            print(f"[doc] {p.name} -> {d.relative_to(ROOT)}")
        elif ext in VIDEO_EXTS:
            if p.stat().st_size <= LIMIT:
                d = safe_move(p, VIDEOS)
                print(f"[video] {p.name} -> {d.relative_to(ROOT)}")
            else:
                big.append(p)
    return big


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--all"
    BACKUP.mkdir(parents=True, exist_ok=True)
    big = organize()
    if mode == "--organize-only":
        print(f"\n{len(big)} large videos pending compression:")
        for p in sorted(big, key=lambda x: x.stat().st_size, reverse=True):
            print(f"  {p.stat().st_size / 1024 / 1024:.0f} MB  {p.name}")
        return
    for p in sorted(big, key=lambda x: x.stat().st_size):
        out = compress(p)
        d = safe_move(p, BACKUP)
        print(f"[backup] original -> {d.relative_to(ROOT)} (ignored by git)")


if __name__ == "__main__":
    main()
