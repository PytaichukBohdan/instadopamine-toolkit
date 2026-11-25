"""Time describes sampled evidence, never a person's current habits."""
from datetime import date, datetime, timezone
import html

RECENCY = {'recent': 'Recent · within 180 days', 'older': 'Older · 181–730 days',
           'historical': 'Historical · over 730 days', 'unknown': 'Date unknown'}


def summarize_time(observations, as_of):
    cutoff = date.fromisoformat(as_of)
    sources, days, occasions = {}, set(), set()
    unknown_dates, unknown_occasions = set(), set()
    for row in observations:
        source = row['source_id']
        if not isinstance(source, str) or not source:
            raise ValueError('Temporal evidence needs a source ID')
        value = row.get('published_at')
        day = None
        if value is not None:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.utcoffset() is None:
                raise ValueError('Evidence date needs a timezone')
            day = parsed.astimezone(timezone.utc).date()
            if day > cutoff:
                raise ValueError('Evidence cannot postdate the analysis')
            days.add(day)
        else:
            unknown_dates.add(source)
        occasion = row.get('occasion_id')
        if occasion:
            if not row.get('occasion_basis'):
                raise ValueError('An occasion grouping needs an evidence basis')
            occasions.add(occasion)
        else:
            unknown_occasions.add(source)
        identity = (day, occasion)
        if source in sources and sources[source] != identity:
            raise ValueError('Duplicate source has conflicting temporal metadata')
        sources[source] = identity
    last = max(days) if days else None
    age = (cutoff - last).days if last else None
    recency = 'unknown' if age is None else 'recent' if age <= 180 else 'older' if age <= 730 else 'historical'
    recurrence = 'across_occasions' if len(occasions) >= 2 else 'one_occasion' if occasions and not unknown_occasions else 'not_established'
    return dict(as_of=as_of, first_observed=min(days).isoformat() if days else None,
                last_observed=last.isoformat() if last else None, age_days=age, recency=recency,
                distinct_sources=len(sources), distinct_publication_days=len(days),
                known_occasions=len(occasions), unknown_occasion_sources=len(unknown_occasions),
                undated_sources=len(unknown_dates), recurrence=recurrence)


def render_time(summary):
    if not summary:
        return ''
    s = summary
    span = f"{s['first_observed']} → {s['last_observed']}" if s['first_observed'] else 'Unknown'
    recurrence = {'across_occasions': 'Across documented occasions', 'one_occasion': 'One documented occasion',
                  'not_established': 'Independent occasions not established'}[s['recurrence']]
    unknown = f" · {s['undated_sources']} undated source(s)" if s['undated_sources'] else ''
    return f'''<div class="temporal-evidence"><span class="recurrence-badge">{html.escape(RECENCY[s['recency']])}</span>
<p>First → last published: {html.escape(span)}{unknown}<br>
{s['distinct_sources']} source(s) · {s['distinct_publication_days']} publication day(s) · {s['known_occasions']} documented occasion(s)<br>
{recurrence} · assessed {s['as_of']}</p><small>Latest known publication, not filming date or proof of a current habit.</small></div>'''
