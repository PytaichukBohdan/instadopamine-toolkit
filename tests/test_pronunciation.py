import unittest

from instadna.pronunciation import check_text, make_ledger, plain, validate_ledger


class PronunciationTests(unittest.TestCase):
    def test_preserves_ukrainian_letters(self):
        self.assertEqual(plain("Пої́хали! Мій."), "Поїхали! Мій.")
        self.assertEqual(check_text("Пої́хали! Мій.", "Поїхали! Мій."), [])

    def test_rejects_missing_extra_and_misplaced_marks(self):
        for text in ["Поїхали", "По́ї́хали", "Всім́", "́Друзі", "Др́узі", "ти́"]:
            with self.subTest(text=text):
                self.assertTrue(check_text(text))

    def test_checks_compound_components(self):
        self.assertEqual(check_text("Ко́ка-ко́ла."), [])
        self.assertTrue(check_text("Кока-ко́ла."))

    def test_spelling_and_numbers_are_not_silently_fixed(self):
        self.assertTrue(check_text("Дру́зі!", "Друзі."))
        self.assertTrue(check_text("6 мільйо́нів"))
        self.assertTrue(check_text("YouTube"))

    def test_repeated_occurrences_each_need_a_basis(self):
        with self.assertRaises(ValueError):
            make_ledger(b"request", ["Дру́зі, дру́зі!"], [["context reviewed"]], "agent")
        ledger = make_ledger(b"request", ["Дру́зі, дру́зі!"], [["first", "second"]], "agent")
        entries = ledger["sections"][0]["words"]
        self.assertNotEqual(entries[0]["offset"], entries[1]["offset"])
        validate_ledger(b"request", ["Дру́зі, дру́зі!"], ledger)

    def test_request_and_text_tampering_fail(self):
        ledger = make_ledger(b"request", ["Пої́хали!"], [["context reviewed"]], "agent")
        with self.assertRaises(ValueError):
            validate_ledger(b"request changed", ["Пої́хали!"], ledger)
        with self.assertRaises(ValueError):
            validate_ledger(b"request", ["Пої́хали?"], ledger)


if __name__ == "__main__":
    unittest.main()
