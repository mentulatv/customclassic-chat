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


def test_drop_scene_blanks_the_dim_scene_but_keeps_chat_text_and_bands():
    import numpy as np
    from reader import drop_scene, BACKGROUNDS
    img = np.full((30, 100, 3), 40, np.uint8)       # the scene through the chat box
    img[2:6, 10:20] = 255                            # white map chat
    img[2:6, 60:70] = (120, 110, 100)                # a name tag behind the chat
    img[8:12, 30:40] = (0, 255, 0)                   # a whisper
    img[8:12, 60:70] = (190, 190, 190)               # a grey speech bubble behind it
    img[20:28] = BACKGROUNDS["super_megaphone"]      # a megaphone band...
    img[22:26, 10:20] = (119, 0, 66)                 # ...and its dark text
    out = drop_scene(img)
    assert (out[2:6, 10:20] == 255).all() and (out[8:12, 30:40] == img[8:12, 30:40]).all()
    assert (out[2:6, 60:70] == 0).all() and (out[8:12, 60:70] == 0).all()
    assert (out[20:28] == img[20:28]).all()


def test_drop_scene_follows_a_fade():
    import numpy as np
    from reader import drop_scene
    img = np.full((10, 50, 3), 20, np.uint8)
    img[2:6, 5:15] = 178                             # white text, the whole picture dimmed by a fade
    img[2:6, 30:40] = 80                             # the scene behind, dimmed too
    out = drop_scene(img)
    assert (out[2:6, 5:15] == 178).all() and (out[2:6, 30:40] == 0).all()
