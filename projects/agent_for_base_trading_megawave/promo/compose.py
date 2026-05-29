from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMO_DIR = ROOT / "promo"
ASSET_DIR = PROMO_DIR / "assets"
OUTPUT_DIR = PROMO_DIR / "output"
RAW_DIR = OUTPUT_DIR / "raw"
SCRIPT = PROMO_DIR / "script.zh.md"
SRT = PROMO_DIR / "subtitles.zh.srt"


def main() -> None:
    parser = argparse.ArgumentParser(description="Compose promo footage, voiceover, subtitles, and background music.")
    parser.add_argument("--skip-audio", action="store_true")
    args = parser.parse_args()

    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not args.skip_audio:
        build_audio_assets()
    build_video("16x9", 1920, 1080)
    build_video("9x16", 1080, 1920)
    build_cover()


def build_audio_assets() -> None:
    text = "\n".join(line.strip() for line in SCRIPT.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#"))
    voice_mp3 = ASSET_DIR / "voiceover.zh.mp3"
    bgm_mp3 = ASSET_DIR / "bgm.mp3"
    logo = ASSET_DIR / "logo.png"

    run(["edge-tts", "--voice", "zh-CN-XiaoxiaoNeural", "--rate", "+8%", "--text", text, "--write-media", str(voice_mp3)], "voiceover synthesis")
    duration = probe_duration(voice_mp3)
    if duration < 10:
        raise RuntimeError(f"voiceover synthesis produced invalid short audio: {duration:.2f}s")
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=196:duration=80:sample_rate=44100",
            "-af",
            "volume=0.035,afade=t=in:st=0:d=1,afade=t=out:st=76:d=3",
            "-codec:a",
            "libmp3lame",
            str(bgm_mp3),
        ],
        "background music generation",
    )
    build_logo(logo)


def build_video(variant: str, width: int, height: int) -> None:
    raw = RAW_DIR / f"megawave-demo-{variant}.webm"
    if not raw.exists():
        raise FileNotFoundError(f"missing raw recording: {raw}")
    output = OUTPUT_DIR / f"megawave-promo-{variant}.mp4"
    voice = ASSET_DIR / "voiceover.zh.mp3"
    bgm = ASSET_DIR / "bgm.mp3"
    duration = probe_duration(raw)
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=#f7f7f4,"
        f"subtitles={quote_filter_path(SRT)}:force_style='FontName=Hiragino Sans GB,FontSize={8 if variant == '16x9' else 7},"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H90000000,BorderStyle=1,Outline=0.7,Shadow=0,MarginV=14,Alignment=2'"
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(raw),
            "-i",
            str(voice),
            "-i",
            str(bgm),
            "-filter_complex",
            f"[0:v]{vf}[v];[1:a]volume=1.0,apad[a1];[2:a]volume=0.30,aloop=loop=-1:size=2147483647[a2];[a1][a2]amix=inputs=2:duration=first:dropout_transition=2[a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-t",
            f"{duration:.3f}",
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            str(output),
        ],
        f"compose {variant}",
    )


def build_cover() -> None:
    source = RAW_DIR / "megawave-demo-16x9.webm"
    cover = OUTPUT_DIR / "cover.png"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", "00:00:04", "-i", str(source), "-frames:v", "1", str(cover)], "cover frame export")


def build_logo(path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1024, 1024), "#111111")
    draw = ImageDraw.Draw(image)
    for y in range(320, 670, 90):
        draw.arc((210, y - 120, 814, y + 120), 8, 172, fill="#58e7f0", width=34)
        draw.arc((260, y - 70, 764, y + 70), 8, 172, fill="#e8fbff", width=20)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 86)
    except Exception:
        font = ImageFont.load_default()
    draw.text((238, 720), "Megawave", fill="#ffffff", font=font)
    image.save(path)


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        check=True,
        text=True,
        capture_output=True,
    )
    return float(result.stdout.strip())


def quote_filter_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def run(cmd: list[str], label: str) -> None:
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"{label} failed with exit code {exc.returncode}") from exc


if __name__ == "__main__":
    main()
