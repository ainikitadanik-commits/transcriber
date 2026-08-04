import unittest

import torch

from transcriber.gigaam_realtime import GigaAMInMemoryAdapter


class FakeRealtimeModel:
    _device = torch.device("cpu")
    _dtype = torch.float32

    def forward(self, waveform, length):
        self.waveform = waveform
        self.length = length
        return waveform, length

    def _decode(
        self,
        encoded,
        encoded_length,
        wav_length,
        word_timestamps,
    ):
        self.decode_args = (
            encoded,
            encoded_length,
            wav_length,
            word_timestamps,
        )
        return [("  распознанный текст  ", None)]


class GigaAMRealtimeTests(unittest.TestCase):
    def test_adapter_decodes_pcm_directly_without_files(self):
        model = FakeRealtimeModel()
        adapter = GigaAMInMemoryAdapter(model)

        result = adapter("system", b"\0\0" * 16_000, 16_000)

        self.assertEqual(result.text, "распознанный текст")
        self.assertEqual(result.words, ())
        self.assertEqual(tuple(model.waveform.shape), (1, 16_000))
        self.assertEqual(int(model.length.item()), 16_000)
        self.assertTrue(model.decode_args[-1])

    def test_adapter_enforces_pcm_contract_and_short_window(self):
        adapter = GigaAMInMemoryAdapter(FakeRealtimeModel())

        with self.assertRaisesRegex(ValueError, "16 кГц"):
            adapter("system", b"\0\0", 8_000)
        with self.assertRaisesRegex(ValueError, "int16"):
            adapter("system", b"\0", 16_000)
        with self.assertRaisesRegex(ValueError, "25 секунд"):
            adapter("system", b"\0\0" * (25 * 16_000 + 1), 16_000)

    def test_adapter_rejects_unexpected_gigaam_contract(self):
        with self.assertRaisesRegex(TypeError, "_device"):
            GigaAMInMemoryAdapter(object())


if __name__ == "__main__":
    unittest.main()
