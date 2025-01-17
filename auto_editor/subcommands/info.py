import sys
import json
import os.path

from typing import Optional


def info_options(parser):
    parser.add_argument("--json", flag=True, help="Export info in JSON format.")
    parser.add_argument(
        "--include-vfr",
        "--has-vfr",
        flag=True,
        help="Display the number of Variable Frame Rate (VFR) frames.",
    )
    parser.add_argument(
        "--include-timebase",
        "--has-timebase",
        flag=True,
        help="Show what timebase the video streams have.",
    )
    parser.add_argument(
        "--ffmpeg-location", default=None, help="Point to your custom ffmpeg file."
    )
    parser.add_argument(
        "--my-ffmpeg",
        flag=True,
        help="Use the ffmpeg on your PATH instead of the one packaged.",
    )
    parser.add_required(
        "input", nargs="*", help="The path to a file you want inspected."
    )
    return parser


def main(sys_args=sys.argv[1:]):
    from auto_editor.utils.log import Log
    from auto_editor.utils.func import aspect_ratio
    from auto_editor.vanparse import ArgumentParser
    from auto_editor.ffwrapper import FFmpeg, FileInfo

    parser = info_options(ArgumentParser("info"))
    args = parser.parse_args(sys_args)

    ffmpeg = FFmpeg(args.ffmpeg_location, args.my_ffmpeg, False)

    def aspect_str(w: Optional[str], h: Optional[str]) -> str:
        if w is None or h is None:
            return ""
        w_, h_ = aspect_ratio(int(w), int(h))
        if w_ is None:
            return ""
        return f" ({w_}:{h_})"

    file_info = {}

    for file in args.input:
        text = ""
        if os.path.exists(file):
            text += f"file: {file}\n"
        else:
            Log().error(f"Could not find file: {file}")

        inp = FileInfo(file, ffmpeg)

        file_info[file] = {
            "video": [],
            "audio": [],
            "subtitle": [],
            "container": {},
        }

        if len(inp.video_streams) > 0:
            text += f" - video tracks: {len(inp.video_streams)}\n"

        for track, stream in enumerate(inp.video_streams):
            text += f"   - Track #{track}\n"
            text += f"     - codec: {stream.codec}\n"

            vid = {}
            vid["codec"] = stream.codec

            import av

            container = av.open(file, "r")
            pix_fmt = container.streams.video[track].pix_fmt
            text += f"     - pix_fmt: {pix_fmt}\n"
            vid["pix_fmt"] = pix_fmt

            if args.include_timebase:
                time_base = container.streams.video[track].time_base
                text += f"     - time_base: {time_base}\n"
                vid["time_base"] = time_base

            if stream.fps is not None:
                text += f"     - fps: {stream.fps}\n"
                vid["fps"] = float(stream.fps)

            w = stream.width
            h = stream.height

            if w is not None and h is not None:
                text += f"     - resolution: {w}x{h}{aspect_str(w, h)}\n"

                vid["width"] = int(w)
                vid["height"] = int(h)
                vid["aspect_ratio"] = aspect_ratio(int(w), int(h))

            if stream.bitrate is not None:
                text += f"     - bitrate: {stream.bitrate}\n"
                vid["bitrate"] = stream.bitrate
            if stream.lang is not None:
                text += f"     - lang: {stream.lang}\n"
                vid["lang"] = stream.lang

            file_info[file]["video"].append(vid)

        if len(inp.audio_streams) > 0:
            text += f" - audio tracks: {len(inp.audio_streams)}\n"

        for track, stream in enumerate(inp.audio_streams):
            aud = {}

            text += f"   - Track #{track}\n"
            text += f"     - codec: {stream.codec}\n"
            text += f"     - samplerate: {stream.samplerate}\n"

            aud["codec"] = stream.codec
            aud["samplerate"] = int(stream.samplerate)

            if stream.bitrate is not None:
                text += f"     - bitrate: {stream.bitrate}\n"
                aud["bitrate"] = stream.bitrate

            if stream.lang is not None:
                text += f"     - lang: {stream.lang}\n"
                aud["lang"] = stream.lang

            file_info[file]["audio"].append(aud)

        if len(inp.subtitle_streams) > 0:
            text += f" - subtitle tracks: {len(inp.subtitle_streams)}\n"

        for track, stream in enumerate(inp.subtitle_streams):
            sub = {}

            text += f"   - Track #{track}\n"
            text += f"     - codec: {stream.codec}\n"
            sub["codec"] = stream.codec
            if stream.lang is not None:
                text += f"     - lang: {stream.lang}\n"
                sub["lang"] = stream.lang

            file_info[file]["subtitle"].append(sub)

        if (
            len(inp.video_streams) + len(inp.audio_streams) + len(inp.subtitle_streams)
            == 0
        ):
            text += "Invalid media.\n"
            file_info[file] = {"media": "invalid"}
        else:
            text += " - container:\n"

            cont = file_info[file]["container"]

            if inp.duration is not None:
                text += f"   - duration: {inp.duration}\n"
                cont["duration"] = inp.duration
            if inp.bitrate is not None:
                text += f"   - bitrate: {inp.bitrate}\n"
                cont["bitrate"] = inp.bitrate

            if args.include_vfr:
                if not args.json:
                    print(text, end="")
                text = ""
                fps_mode = ffmpeg.pipe(
                    [
                        "-i",
                        file,
                        "-hide_banner",
                        "-vf",
                        "vfrdet",
                        "-an",
                        "-f",
                        "null",
                        "-",
                    ]
                )
                fps_mode = fps_mode.strip()

                if "VFR:" in fps_mode:
                    fps_mode = (fps_mode[fps_mode.index("VFR:") :]).strip()

                text += f"   - {fps_mode}\n"
                cont["fps_mode"] = fps_mode

        if not args.json:
            print(text)

    if args.json:
        json_object = json.dumps(file_info, indent=4)
        print(json_object)


if __name__ == "__main__":
    main()
