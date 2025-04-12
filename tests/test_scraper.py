from app.scraper import compute_similarity, is_blocked


def test_compute_similarity():
    # Basic similarity should return a float value between 0 and 1
    similarity = compute_similarity("hello", "hello world")
    assert 0 < similarity <= 1


def test_is_blocked():
    # Should return True for pages that mention "captcha"
    blocked_content = "Please verify that you are human, captcha validation required."
    assert is_blocked(blocked_content)
