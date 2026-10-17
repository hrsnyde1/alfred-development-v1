import unittest

import calculator


class CalculatorTests(unittest.TestCase):
    def test_add(self):
        self.assertEqual(calculator.add(7, 3), 10)

    def test_subtract(self):
        # Intentional red test for the one-file Developer V1 task.
        self.assertEqual(calculator.subtract(7, 3), 4)
