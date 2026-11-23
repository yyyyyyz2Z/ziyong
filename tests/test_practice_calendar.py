import unittest

from backend.services.practice_calendar import calendar_file


class PracticeCalendarTests(unittest.TestCase):
    def test_weekly_all_day_export_preserves_dates_and_utf8(self):
        content = calendar_file(7, {"weekdays":[0,2,4], "start_date":"2026-11-24"}, [
            {"title":"手指衔接练习" * 20, "detail":"换指，放松; 慢练\nBEGIN:VEVENT"},
        ])
        self.assertTrue(all(len(line) <= 75 for line in content.split(b'\r\n')))
        unfolded = content.decode().replace('\r\n ', '')
        self.assertIn('DTSTART;VALUE=DATE:20261125\r\n', unfolded)
        self.assertIn('DTEND;VALUE=DATE:20261126\r\n', unfolded)
        self.assertIn('RRULE:FREQ=WEEKLY;WKST=MO;BYDAY=MO,WE,FR', unfolded)
        self.assertIn('手指衔接练习' * 20, unfolded)
        self.assertIn(r'换指，放松\; 慢练\nBEGIN:VEVENT', unfolded)
        self.assertEqual(unfolded.count('\r\nBEGIN:VEVENT\r\n'), 1)
        with self.assertRaisesRegex(ValueError, '先保存'):
            calendar_file(7, None, [])

    def test_project_weekdays_and_end_date_limit_recurrence(self):
        content = calendar_file(7, {'weekdays':[0,2,4], 'start_date':'2026-11-24', 'end_date':'2026-12-20'}, [
            {'id':'a','title':'周三练节奏','detail':'慢练','weekdays':[2]},
            {'id':'b','title':'周五练换指','detail':'三遍','weekdays':[4]},
        ]).decode().replace('\r\n ', '')
        self.assertIn('DTSTART;VALUE=DATE:20261125',content)
        self.assertIn('DTSTART;VALUE=DATE:20261127',content)
        self.assertIn('BYDAY=WE;UNTIL=20261220',content)
        self.assertIn('BYDAY=FR;UNTIL=20261220',content)
        self.assertEqual(content.count('\r\nBEGIN:VEVENT\r\n'),2)


if __name__ == '__main__':
    unittest.main()
