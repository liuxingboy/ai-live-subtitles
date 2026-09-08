"""Bounded item-based subtitle pairing; never pair by arrival count."""
from collections import OrderedDict
from dataclasses import dataclass


@dataclass
class Segment:
    source: str = ''
    translation: str = ''
    source_final: bool = False
    translation_final: bool = False


class SubtitleManager:
    def __init__(self, partial=False, max_items=64):
        self.partial = partial
        self.max_items = max_items
        self.segments = OrderedDict()
        self.links = {}

    def reset(self):
        self.segments.clear()
        self.links.clear()

    def _item(self, key):
        if key not in self.segments:
            self.segments[key] = Segment()
        while len(self.segments) > self.max_items:
            old, _ = self.segments.popitem(last=False)
            self.links = {k: v for k, v in self.links.items() if k != old and v != old}
        return self.segments[key]

    def feed(self, event):
        kind = event.get('type', '')
        if kind == '_session_reset':
            self.reset()
            return
        if kind == 'conversation.item.created':
            item = event.get('item', {})
            item_id, previous = item.get('id'), event.get('previous_item_id')
            if item.get('role') == 'user' and item_id:
                self._item(item_id)
            elif item.get('role') == 'assistant' and item_id and previous:
                self.links[item_id] = previous
                target = self._item(previous)
                # Translation can precede its association event.
                orphan = self.segments.pop(item_id, None) if item_id != previous else None
                if orphan:
                    target.translation = orphan.translation
                    target.translation_final = orphan.translation_final
                # Bound aliases as well as subtitle text during long sessions.
                if len(self.links) > self.max_items:
                    self.links.pop(next(iter(self.links)))
            return
        source = kind.startswith('conversation.item.input_audio_transcription.')
        translation = kind in ('response.text.text', 'response.text.done')
        if not source and not translation:
            return
        item_id = event.get('item_id')
        if not item_id:
            return
        final = kind.endswith('.completed') if source else kind.endswith('.done')
        if not final and not self.partial:
            return
        if source and not kind.endswith(('.completed', '.text')):
            return
        key = item_id if source else self.links.get(item_id, item_id)
        segment = self._item(key)
        text = event.get('transcript' if source and final else 'text', '')
        if not final:
            text += event.get('stash', '')
        # Do not allow delayed partial events to overwrite a final result.
        attr = 'source' if source else 'translation'
        if not getattr(segment, attr + '_final') or final:
            setattr(segment, attr, text)
            setattr(segment, attr + '_final', final)

    def snapshot(self):
        for key in reversed(self.segments):
            segment = self.segments[key]
            if segment.source or segment.translation:
                return segment.source, segment.translation
        return '', ''
