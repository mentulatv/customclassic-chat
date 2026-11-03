import numpy as np
from PIL import Image

from reader import chat_box_by_scrollbar


def game_chat(width=900, height=400, left=120, right=700, top=180, bottom=330):
    """A made-up lower game window: scenery, the chat's dark lines, its scrollbar (a grey track
    with blue arrow buttons at both ends) and the near-black frame line under it, no time stamps."""
    rng = np.random.default_rng(1)
    a = rng.integers(30, 200, (height, width, 3)).astype(np.uint8)  # scenery
    a[top:bottom, left:right] = (20, 24, 40)
    a[top:bottom, right:right + 14] = (170, 170, 170)  # the track
    a[top:top + 14, right + 1:right + 14] = (60, 90, 200)  # the arrows
    a[bottom - 14:bottom, right + 1:right + 14] = (60, 90, 200)
    a[bottom + 3, left:right + 14] = (12, 12, 12)  # the frame line
    return Image.fromarray(a)


def test_chat_found_by_its_scrollbar():
    box = chat_box_by_scrollbar(game_chat())
    assert box and abs(box["left"] - 120) <= 3 and box["left"] + box["width"] == 699
    assert abs(box["top"] - 178) <= 2 and abs(box["top"] + box["height"] - 331) <= 2


def test_no_scrollbar_no_chat():
    a = np.random.default_rng(2).integers(30, 200, (400, 900, 3)).astype(np.uint8)
    assert chat_box_by_scrollbar(Image.fromarray(a)) is None


def test_a_longer_grey_bar_in_the_scene_doesnt_hide_the_chat():
    img = game_chat(left=200, right=760)
    a = np.asarray(img).copy()
    a[20:380, 100:114] = (170, 170, 170)  # a taller "scrollbar" with nothing chat-wide beside it
    a[20:34, 101:114] = a[366:380, 101:114] = (60, 90, 200)
    a[383, 40:114] = (12, 12, 12)
    box = chat_box_by_scrollbar(Image.fromarray(a))
    assert box and box["left"] + box["width"] == 759
