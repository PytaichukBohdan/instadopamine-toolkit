import unittest
from instadna.temporal import summarize_time


def observation(source, date=None, occasion=None):
    return dict(source_id=source, published_at=date, occasion_id=occasion,
                occasion_basis='Documented story sequence' if occasion else None)


class TemporalTests(unittest.TestCase):
    def test_duplicate_frames_and_multi_day_trip_are_not_independent_occasions(self):
        rows = [observation('A','2024-05-17T12:00:00Z','trip'),
                observation('A','2024-05-17T12:00:00Z','trip'),
                observation('B','2024-05-18T12:00:00Z','trip')]
        s = summarize_time(rows, '2026-10-02')
        self.assertEqual((s['distinct_sources'],s['distinct_publication_days'],s['known_occasions']), (2,2,1))
        self.assertEqual(s['recency'], 'historical')
        self.assertEqual(s['recurrence'], 'one_occasion')

    def test_recent_one_off_and_historical_recurrence_are_independent_axes(self):
        recent = summarize_time([observation('A','2026-09-19T00:00:00Z','shoot')], '2026-10-02')
        old = summarize_time([observation('A','2023-09-01T00:00:00Z','trip-a'),observation('B','2024-05-01T00:00:00Z','trip-b')], '2026-10-02')
        self.assertEqual((recent['recency'],recent['recurrence']),('recent','one_occasion'))
        self.assertEqual((old['recency'],old['recurrence']),('historical','across_occasions'))

    def test_missing_dates_and_event_groupings_stay_unknown(self):
        s = summarize_time([observation('A'),observation('B')], '2026-10-02')
        self.assertIsNone(s['last_observed'])
        self.assertEqual((s['undated_sources'],s['unknown_occasion_sources']), (2,2))
        self.assertEqual(s['recurrence'], 'not_established')
        mixed = summarize_time([observation('A'),observation('B','2026-09-01T00:00:00Z','event')], '2026-10-02')
        self.assertEqual(mixed['undated_sources'],1)
        self.assertEqual(mixed['recency'],'recent')
        self.assertEqual(mixed['recurrence'],'not_established')

    def test_conflicting_duplicates_future_dates_and_unfounded_grouping_fail(self):
        for rows in [[observation('A','2026-09-01T00:00:00Z'),observation('A','2026-09-02T00:00:00Z')],
                     [observation('A','2026-10-03T00:00:00Z')],
                     [dict(source_id='A',occasion_id='trip')]]:
            with self.assertRaises(ValueError):summarize_time(rows,'2026-10-02')

    def test_utc_day_and_inclusive_recency_boundary(self):
        s = summarize_time([observation('A','2026-04-05T00:30:00+01:00')], '2026-10-02')
        self.assertEqual(s['last_observed'],'2026-04-04')
        self.assertEqual(s['age_days'],181)
        self.assertEqual(s['recency'],'older')
        s = summarize_time([observation('A','2026-04-05T00:00:00Z')], '2026-10-02')
        self.assertEqual(s['age_days'],180)
        self.assertEqual(s['recency'],'recent')
