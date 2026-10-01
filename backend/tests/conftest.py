import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

# Unit/API tests must not load/download embedding models or contact providers.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
rag = ModuleType('rag')
for name in ('retrieve_case_examples', 'retrieve_case_phrases', 'retrieve_conclusion_examples',
             'get_hints', 'get_categories', 'get_auditors', 'save_report_to_memory'):
    setattr(rag, name, Mock(return_value=[]))
sys.modules['rag'] = rag
imaging = ModuleType('imaging')
sys.modules['imaging'] = imaging
