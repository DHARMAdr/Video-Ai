"""
Tests for following kill-feed lines by their contents (namefeed.line_times).

The pictures are drawn here with made-up names, so no game footage is stored in the project.
HOW TO IMPROVE: add pictures with a moving background behind a see-through feed.
"""

import unittest

import numpy as np

from shortsforge import namefeed

try:
    import cv2
except ImportError:                                       # pragma: no cover
    cv2 = None

GP = {"name_threshold": 0.70, "victim_gap": 40}
GEOMETRY = {"frame_w": 1920, "x0": 1440}


def picture(*victims):
    """A grey feed picture with one line per victim, all killed by ME."""
    image = np.full((200, 480), 90, np.uint8)
    for row, victim in enumerate(victims):
        y = 40 + row * 32
        cv2.putText(image, "KILLER_ME", (80, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 255, 1)
        cv2.putText(image, victim, (220, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 255, 1)
    return image


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class FeedLines(unittest.TestCase):
    def times(self, frames):
        template = picture("x")[24:46, 78:196]
        return namefeed.line_times(frames, template, GP, GEOMETRY, 4)

    def test_one_line_replaced_by_another_is_two_kills(self):
        # The number of lines stays 1 the whole time, so counting would see only one kill.
        frames = [picture()] * 4 + [picture("ALPHA_7")] * 8 + [picture("ZZQ_OMEGA")] * 8
        self.assertEqual(self.times(frames), [1.0, 3.0])

    def test_a_line_that_moves_up_is_not_new(self):
        frames = [picture("ALPHA_7", "ZZQ_OMEGA")] * 4 + [picture("ZZQ_OMEGA")] * 4
        self.assertEqual(self.times(frames), [0.0, 0.0])

    def test_a_short_flash_does_not_count_twice_and_noise_is_ignored(self):
        frames = [picture("ALPHA_7")] * 4 + [picture()] * 3 + [picture("ALPHA_7")] * 4
        self.assertEqual(self.times(frames), [0.0])
        self.assertEqual(self.times([picture()] * 3 + [picture("ALPHA_7")] + [picture()] * 6), [])


if __name__ == "__main__":
    unittest.main()
