"""Checks how well CustomClassic Chat fits and reads the game at its current resolution and UI Size.

Run it with the game in front (python tests/fitcheck.py). It reads the game window once, the
way CustomClassic Chat does (text only, nothing saved), and prints the game's size, the chat
box it has saved, a fresh measurement of the chat box, and how many chat lines read cleanly.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import customclassic_chat as mc  # noqa: E402
import reader as core  # noqa: E402


def main() -> None:
    g = mc.game_geometry()
    if not g:
        sys.exit("The game isn't open (no window titled MapleStory).")
    cap = mc.GameCapture(g["hwnd"])
    frame = None
    for _ in range(40):
        time.sleep(0.2)
        frame = cap.latest()
        if frame is not None:
            break
    cap.stop()
    if frame is None:
        sys.exit("Windows gave no picture of the game window.")
    c, ox, oy = g["client"], g["ox"], g["oy"]
    print(f"game: {c['width']}x{c['height']} at ({c['left']}, {c['top']})")
    saved = mc.load_settings()["box"]
    print("saved fit:", saved if saved and (saved["cw"], saved["ch"]) == (c["width"], c["height"]) else
          f"none for this size ({saved and (saved['cw'], saved['ch'])})")

    rd = core.Reader(core.Config.load())
    top = int(c["height"] * 0.35)
    found = mc.find_lines(mc.frame_image(frame, ox, oy + top, ox + c["width"], oy + c["height"]), rd)
    if not found:
        sys.exit("fresh fit: no chat box found (the chat needs at least two time-stamped lines showing).")
    box, pitch = found
    box = {**box, "top": box["top"] + top}
    print(f"fresh fit: left {box['left']} top {box['top']} width {box['width']} height {box['height']}, "
          f"line {pitch}, scrollbar {box.get('bar')}")
    img = mc.frame_image(frame, ox + box["left"], oy + box["top"], ox + box["left"] + box["width"],
                         oy + box["top"] + box["height"])
    read = rd.read(img)
    lines = core.merge_wrapped(mc.trim_scene(read, pitch), img.height, img.width)
    cfg = rd.cfg
    msgs = mc.messages_from(lines, mc.Dedupe(), time.time(), (cfg.colors, cfg.backgrounds))
    stamped = sum(1 for ln in lines if core.TIMESTAMP.match(ln.text))
    print(f"read: {len(lines)} lines ({stamped} with a time stamp) -> {len(msgs)} messages")
    kinds = {}
    for m in msgs:
        kinds[m["kind"]] = kinds.get(m["kind"], 0) + 1
    print("by kind:", kinds)
    if saved and (saved["cw"], saved["ch"]) == (c["width"], c["height"]):
        off = max(abs(saved["dx"] - box["left"]), abs((c["height"] - saved["dy"]) - box["top"]) - box["height"])
        print("saved fit matches the fresh one" if abs(saved["dx"] - box["left"]) <= 6 and
              abs(saved["line"] - pitch) <= pitch * 0.2 else f"saved fit is off (by about {off}px): it will refit")


if __name__ == "__main__":
    main()
