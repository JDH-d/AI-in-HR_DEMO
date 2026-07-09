import shutil
import unittest
from pathlib import Path

from workflow import WorkflowService


class WorkflowServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path.cwd() / '.tmp_tests' / self._testMethodName
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.temp_dir / 'workflow.db'
        self.service = WorkflowService(str(self.db_path))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_creates_pto_request_for_vacation_dates(self) -> None:
        result = self.service.try_create(
            'I need vacation from 01/04 to 03/04',
            created_by='demo-user',
        )

        self.assertIsNotNone(result)
        self.assertEqual(result['type'], 'PTO')
        self.assertEqual(result['period_or_date'], 'from 01/04 to 03/04')
        self.assertEqual(result['status'], 'pending')

    def test_creates_pto_request_for_generic_leave_dates(self) -> None:
        result = self.service.try_create(
            'I need leave from 01/04 to 03/04',
            created_by='demo-user',
        )

        self.assertIsNotNone(result)
        self.assertEqual(result['type'], 'PTO')

    def test_creates_sick_request(self) -> None:
        result = self.service.try_create(
            'I want sick leave tomorrow',
            created_by='demo-user',
        )

        self.assertIsNotNone(result)
        self.assertEqual(result['type'], 'Sick')
        self.assertEqual(result['period_or_date'], 'tomorrow')

    def test_policy_question_does_not_create_request(self) -> None:
        result = self.service.try_create(
            'Tell me about the vacation policy',
            created_by='demo-user',
        )

        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
