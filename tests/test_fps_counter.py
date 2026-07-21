from handheld.fps_counter import FpsCounter


def test_first_sample_seeds_and_returns_zero():
    c = FpsCounter()
    assert c.sample(100.0) == 0.0


def test_counts_frames_per_elapsed_second():
    c = FpsCounter()
    c.sample(0.0)                 # seed
    for _ in range(30):
        c.tick()
    assert c.sample(1.0) == 30.0


def test_resets_between_samples():
    c = FpsCounter()
    c.sample(0.0)
    c.tick(); c.tick()
    assert c.sample(1.0) == 2.0
    assert c.sample(2.0) == 0.0   # no ticks since last sample


def test_zero_elapsed_returns_zero():
    c = FpsCounter()
    c.sample(5.0)
    c.tick()
    assert c.sample(5.0) == 0.0   # dt == 0, no divide-by-zero
