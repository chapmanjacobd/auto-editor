# Internal Libraries
import os.path
import subprocess

# Typing
from typing import List, Tuple

# Included Libraries
from auto_editor.utils.log import Log
from auto_editor.ffwrapper import FFmpeg, FileInfo
from auto_editor.utils.progressbar import ProgressBar

from auto_editor.utils.encoder import encoders
from auto_editor.utils.video import get_vcodec, video_quality

# From: github.com/PyAV-Org/PyAV/blob/main/av/video/frame.pyx
allowed_pix_fmt = {
    "yuv420p",
    "yuvj420p",
    "rgb48be",
    "rgb48le",
    "rgb64be",
    "rgb64le",
    "rgb24",
    "bgr24",
    "argb",
    "rgba",
    "abgr",
    "bgra",
    "gray",
    "gray8",
    "gray16be",
    "gray16le",
    "rgb8",
    "bgr8",
    "pal8",
}


def pix_fmt_allowed(pix_fmt: str) -> bool:
    return pix_fmt in allowed_pix_fmt


def apply_anchor(
    x: int, y: int, width: int, height: int, anchor: str
) -> Tuple[int, int]:
    if anchor == "ce":
        x = int((x * 2 - width) / 2)
        y = int((y * 2 - height) / 2)
    if anchor == "tr":
        x -= width
    if anchor == "bl":
        y -= height
    if anchor == "br":
        x -= width
        y -= height
    # Pillow uses 'tl' by default
    return x, y


def one_pos_two_pos(
    x: int, y: int, width: int, height: int, anchor: str
) -> Tuple[int, int, int, int]:
    """Convert: x, y, width, height -> x1, y1, x2, y2"""

    if anchor == "ce":
        x1 = x - int(width / 2)
        x2 = x + int(width / 2)
        y1 = y - int(height / 2)
        y2 = y + int(height / 2)

        return x1, y1, x2, y2

    if anchor in ("tr", "br"):
        x1 = x - width
        x2 = x
    else:
        x1 = x
        x2 = x + width

    if anchor in ("tl", "tr"):
        y1 = y
        y2 = y + height
    else:
        y1 = y
        y2 = y - height

    return x1, y1, x2, y2


def render_av(
    ffmpeg: FFmpeg,
    track: int,
    inp: FileInfo,
    args,
    chunks: List[Tuple[int, int, float]],
    fps: float,
    progress: ProgressBar,
    effects,
    rules,
    temp: str,
    log: Log,
) -> Tuple[str, str, bool]:
    try:
        import av
    except ImportError:
        log.import_error("av")
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageChops
    except ImportError:
        log.import_error("Pillow")

    def set_static_assets(all_objects, log: Log):
        # Save reloading the same thing over and over.

        new_objects = []

        for obj in all_objects:
            if obj._type == "text":
                try:
                    obj.font = ImageFont.truetype(obj.font, obj.size)
                except OSError:
                    if obj.font == "default":
                        obj.font = ImageFont.load_default()
                    else:
                        log.error(f"Font '{obj.font}' not found.")

            if obj._type == "image":
                source = Image.open(obj.src)
                source = source.convert("RGBA")
                source = source.rotate(obj.rotate, expand=True)
                source = ImageChops.multiply(
                    source,
                    Image.new(
                        "RGBA", source.size, (255, 255, 255, int(obj.opacity * 255))
                    ),
                )
                obj.src = source

            new_objects.append(obj)

        return new_objects

    def render_objects(sheet, all_objects, index: int, frame, pix_fmt: str):
        img = frame.to_image().convert("RGBA")

        for item in sheet[index]:
            obj = all_objects[item]

            obj_img = Image.new("RGBA", img.size, (255, 255, 255, 0))
            draw = ImageDraw.Draw(obj_img)

            if obj._type == "text":
                text_w, text_h = draw.textsize(obj.content, font=obj.font)
                pos = apply_anchor(obj.x, obj.y, text_w, text_h, "ce")
                draw.text(
                    pos,
                    obj.content,
                    font=obj.font,
                    fill=obj.fill,
                    align=obj.align,
                    stroke_width=obj.stroke,
                    stroke_fill=obj.strokecolor,
                )

            if obj._type == "rectangle":
                draw.rectangle(
                    one_pos_two_pos(obj.x, obj.y, obj.width, obj.height, obj.anchor),
                    fill=obj.fill,
                    width=obj.stroke,
                    outline=obj.strokecolor,
                )

            if obj._type == "ellipse":
                draw.ellipse(
                    one_pos_two_pos(obj.x, obj.y, obj.width, obj.height, obj.anchor),
                    fill=obj.fill,
                    width=obj.stroke,
                    outline=obj.strokecolor,
                )

            if obj._type == "image":
                img_w, img_h = obj.src.size
                pos = apply_anchor(obj.x, obj.y, img_w, img_h, obj.anchor)
                obj_img.paste(obj.src, pos)

            img = Image.alpha_composite(img, obj_img)

        return frame.from_image(img).reformat(format=pix_fmt)

    if chunks[-1][2] == 99999:
        chunks.pop()

    total_frames = chunks[-1][1]
    progress.start(total_frames, "Creating new video")

    container = av.open(inp.path, "r")
    pix_fmt = container.streams.video[track].pix_fmt

    target_pix_fmt = pix_fmt

    if not pix_fmt_allowed(pix_fmt):
        target_pix_fmt = "yuv420p"

    my_codec = get_vcodec(args, inp, rules)

    apply_video_later = True

    if my_codec in encoders:
        apply_video_later = encoders[my_codec]["pix_fmt"].isdisjoint(allowed_pix_fmt)

    if args.scale != 1:
        apply_video_later = False

    log.debug(f"apply video quality settings now: {not apply_video_later}")

    video_stream = container.streams.video[track]
    video_stream.thread_type = "AUTO"

    width = video_stream.width
    height = video_stream.height

    effects.all = set_static_assets(effects.all, log)

    spedup = os.path.join(temp, f"spedup{track}.mp4")

    cmd = [
        "-hide_banner",
        "-y",
        "-f",
        "rawvideo",
        "-c:v",
        "rawvideo",
        "-pix_fmt",
        target_pix_fmt,
        "-s",
        f"{width}*{height}",
        "-framerate",
        str(fps),
        "-i",
        "-",
        "-pix_fmt",
        target_pix_fmt,
    ]

    if apply_video_later:
        cmd.extend(["-c:v", "mpeg4", "-qscale:v", "1"])
    else:
        cmd = video_quality(cmd, args, inp, rules)

    cmd.append(spedup)

    process2 = ffmpeg.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    input_equavalent = 0.0
    output_equavalent = 0
    chunk = chunks.pop(0)

    tou = int(video_stream.time_base.denominator / fps)
    log.debug(f"Tou {tou}")

    seek = 10
    seek_frame = None
    frames_saved = 0

    SEEK_COST = int(
        fps * 5
    )  # Keyframes are usually spread out every 5 seconds or less.
    SEEK_RETRY = SEEK_COST // 2

    try:
        for frame in container.decode(video_stream):
            index = int(frame.time * fps)

            if frame.key_frame:
                log.debug(f"Keyframe {index} {frame.pts}")

            if seek_frame is not None:
                log.debug(f"Skipped {index - seek_frame} frames")
                frames_saved += index - seek_frame
                seek_frame = None

            if index > chunk[1]:
                if chunks:
                    chunk = chunks.pop(0)
                else:
                    break

            if chunk[2] == 99999:
                if chunk[1] - index > SEEK_COST and index > seek:
                    seek = index + SEEK_RETRY

                    seek_frame = index
                    container.seek(chunk[1] * tou, stream=video_stream)
            else:
                input_equavalent += 1 / chunk[2]

            while input_equavalent > output_equavalent:
                if index in effects.sheet:
                    frame = render_objects(
                        effects.sheet, effects.all, index, frame, target_pix_fmt
                    )
                elif pix_fmt != target_pix_fmt:
                    frame = frame.reformat(format=target_pix_fmt)

                in_bytes = frame.to_ndarray().tobytes()
                process2.stdin.write(in_bytes)
                output_equavalent += 1

            if index % 3 == 0:
                progress.tick(index)

        progress.end()
        process2.stdin.close()
        process2.wait()
    except (OSError, BrokenPipeError):
        progress.end()
        ffmpeg.run_check_errors(cmd, log, True)
        log.error("FFmpeg Error!")

    log.debug(f"Total frames saved seeking: {frames_saved}")

    # Unfortunately, scaling has to be a concrete step.
    if args.scale != 1:
        sped_input = os.path.join(temp, f"spedup{track}.mp4")
        spedup = os.path.join(temp, f"scale{track}.mp4")

        cmd = [
            "-i",
            sped_input,
            "-vf",
            f"scale=iw*{args.scale}:ih*{args.scale}",
            spedup,
        ]

        check_errors = ffmpeg.pipe(cmd)
        if "Error" in check_errors or "failed" in check_errors:
            if "-allow_sw 1" in check_errors:
                cmd.insert(-1, "-allow_sw")
                cmd.insert(-1, "1")
            # Run again to show errors even if it might not work.
            ffmpeg.run(cmd)

    return "video", spedup, apply_video_later
