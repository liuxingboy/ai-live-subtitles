import unittest
from subtitle.manager import SubtitleManager


class SubtitleTests(unittest.TestCase):
    def test_out_of_order_translation_is_paired_by_id(self):
        manager = SubtitleManager()
        manager.feed({'type': 'response.text.done', 'item_id': 'zh1', 'text': '你好'})
        self.assertEqual(manager.snapshot(), ('', '你好'))
        manager.feed({'type': 'conversation.item.created', 'item': {'role': 'assistant', 'id': 'zh1'}, 'previous_item_id': 'src1'})
        manager.feed({'type': 'conversation.item.input_audio_transcription.completed', 'item_id': 'src1', 'transcript': 'Hello'})
        self.assertEqual(manager.snapshot(), ('Hello', '你好'))

    def test_new_source_never_reuses_previous_translation(self):
        manager = SubtitleManager()
        for i in (1, 2):
            manager.feed({'type': 'conversation.item.input_audio_transcription.completed', 'item_id': f's{i}', 'transcript': str(i)})
            if i == 1:
                manager.feed({'type': 'conversation.item.created', 'item': {'role': 'assistant', 'id': 't1'}, 'previous_item_id': 's1'})
                manager.feed({'type': 'response.text.done', 'item_id': 't1', 'text': '一'})
        self.assertEqual(manager.snapshot(), ('2', ''))
        manager.feed({'type': 'response.text.done', 'item_id': 't1', 'text': '一。'})
        self.assertEqual(manager.snapshot(), ('2', ''))

    def test_final_replaces_partial_and_stays_final(self):
        manager = SubtitleManager(partial=True)
        manager.feed({'type': 'response.text.text', 'item_id': 'a', 'text': '你', 'stash': '好'})
        self.assertEqual(manager.snapshot(), ('', '你好'))
        manager.feed({'type': 'response.text.done', 'item_id': 'a', 'text': '您好。'})
        manager.feed({'type': 'response.text.text', 'item_id': 'a', 'stash': '错的'})
        self.assertEqual(manager.snapshot(), ('', '您好。'))

    def test_memory_and_session_reset(self):
        manager = SubtitleManager(max_items=4)
        for i in range(20):
            manager.feed({'type': 'conversation.item.created', 'item': {'role': 'assistant', 'id': f't{i}'}, 'previous_item_id': f's{i}'})
            manager.feed({'type': 'response.text.done', 'item_id': f't{i}', 'text': str(i)})
        self.assertLessEqual(len(manager.segments), 4)
        self.assertLessEqual(len(manager.links), 4)
        manager.feed({'type': '_session_reset'})
        self.assertEqual(manager.snapshot(), ('', ''))


if __name__ == '__main__':
    unittest.main()
