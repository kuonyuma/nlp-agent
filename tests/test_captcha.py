from server.auth.captcha import _FONT_SIZE, _IMG_HEIGHT, _IMG_WIDTH


def test_captcha_uses_a_readable_canvas_and_font_for_the_registration_form():
    assert (_IMG_WIDTH, _IMG_HEIGHT, _FONT_SIZE) == (200, 80, 48)
