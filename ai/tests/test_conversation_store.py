import tempfile
import unittest
from pathlib import Path
from praat_ai.conversation_store import ConversationStore


class StoreTests(unittest.TestCase):
    def test_records_survive_reopen_without_credentials_or_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'records.sqlite3'
            store = ConversationStore(path, secrets=['private-test-value'])
            session = store.new_session()
            store.append(session, 'user', {'prompt':'goal'})
            store.append(session, 'report', {'text':'result private-test-value', 'api_key':'private-test-value', 'audio':b'audio bytes'})
            reopened = ConversationStore(path)
            rows = reopened.records(session)
            self.assertEqual(len(rows), 2)
            self.assertNotIn('private-test-value', str(rows))
            self.assertNotIn('audio bytes', str(rows))
            self.assertIn('result', str(rows))


if __name__ == '__main__':
    unittest.main()
