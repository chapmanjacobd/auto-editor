from dataclasses import asdict, fields

from typing import List, Tuple, Dict

from auto_editor.utils.log import Log
from auto_editor.ffwrapper import FileInfo, VideoStream


class Sheet:
    __slots__ = ("all", "sheet")

    def __init__(
        self, pool, inp: FileInfo, chunks: List[Tuple[int, int, float]], log: Log
    ) -> None:

        if len(inp.video_streams) > 0:
            w = inp.video_streams[0].width
            h = inp.video_streams[0].height
            if w is None or h is None:
                width, height = 1280, 720
            else:
                width, height = int(w), int(h)
        else:
            width, height = 1280, 720

        ending = chunks[:]
        if ending[-1][2] == 99999:
            ending.pop()

        end = 0
        if ending:
            end = ending[-1][1]

        _vars = {
            "width": width,
            "height": height,
            "centerX": width // 2,
            "centerY": height // 2,
            "start": 0,
            "end": end,
        }

        self.all = []
        self.sheet = {}

        def _values(val, _type, _vars: Dict[str, int]):
            if val is None:
                return None

            if _type is str:
                return str(val)  # Skip replacing variables with vals.

            for key, item in _vars.items():
                if val == key:
                    return _type(item)

            try:
                _type(val)
            except TypeError as e:
                log.error(str(e))
            except Exception:
                log.error(f"variable '{val}' is not defined.")

            return _type(val)

        for index, obj in enumerate(pool):

            dic_value = asdict(obj)
            dic_type = {}
            for field in fields(obj):
                dic_type[field.name] = field.type

            # Convert to the correct types
            for k, _type in dic_type.items():
                obj.__setattr__(k, _values(dic_value[k], _type, _vars))

            if obj.dur < 1:
                log.error(f"dur's value must be greater than 0. Was '{dur}'.")

            for frame in range(obj.start, obj.start + obj.dur, 1):
                if frame in self.sheet:
                    self.sheet[frame].append(index)
                else:
                    self.sheet[frame] = [index]

            self.all.append(obj)
