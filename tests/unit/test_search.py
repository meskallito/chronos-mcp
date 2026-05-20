"""
Unit tests for event search functionality
"""

import re
from datetime import datetime, timedelta

import pytest

from chronos_mcp.search import SearchOptions, calculate_relevance_score
from chronos_mcp.search import search_events as search_events_func
from chronos_mcp.search import search_events_ranked


class TestSearchOptions:
    def test_search_options_defaults(self):
        """Test SearchOptions with default values"""
        opts = SearchOptions(query="meeting", fields=["summary", "description", "location"])

        assert opts.query == "meeting"
        assert opts.fields == ["summary", "description", "location"]
        assert opts.case_sensitive is False
        assert opts.match_type == "contains"
        assert opts.use_regex is False
        assert opts.date_start is None
        assert opts.date_end is None
        assert opts.max_results is None

    def test_search_options_validation(self):
        """Test SearchOptions validation"""
        # Invalid match type
        with pytest.raises(ValueError) as exc_info:
            SearchOptions(
                query="test",
                fields=["summary", "description", "location"],
                match_type="invalid",
            )
        assert "match_type must be one of" in str(exc_info.value)

        # Valid match types
        for match_type in ["contains", "starts_with", "ends_with", "exact", "regex"]:
            opts = SearchOptions(
                query="test",
                fields=["summary", "description", "location"],
                match_type=match_type,
            )
            assert opts.match_type == match_type

    def test_regex_pattern_compilation(self):
        """Test regex pattern compilation"""
        # Valid regex
        opts = SearchOptions(
            query=r"Meeting.*\d+",
            fields=["summary", "description", "location"],
            use_regex=True,
        )
        assert hasattr(opts, "pattern")
        assert opts.pattern.search("Meeting 123")

        # Invalid regex should raise re.error
        with pytest.raises(re.error):
            SearchOptions(
                query=r"[invalid(",
                fields=["summary", "description", "location"],
                use_regex=True,
            )


class TestSearchEvents:
    def create_test_events(self):
        """Create test event data"""
        base_date = datetime.now()
        return [
            {
                "uid": "1",
                "summary": "Team Meeting",
                "description": "Weekly team sync",
                "location": "Conference Room A",
                "dtstart": base_date - timedelta(days=1),
            },
            {
                "uid": "2",
                "summary": "Project Review",
                "description": "Review project status with team",
                "location": "Zoom",
                "dtstart": base_date + timedelta(days=1),
            },
            {
                "uid": "3",
                "summary": "Client Call",
                "description": "Discuss requirements",
                "location": "Meeting Room B",
                "dtstart": base_date + timedelta(days=3),
            },
            {
                "uid": "4",
                "summary": "Lunch Break",
                "description": "Team lunch outing",
                "location": "Cafeteria",
                "dtstart": base_date,
            },
        ]

    def test_basic_contains_search(self):
        """Test basic contains search"""
        events = self.create_test_events()
        opts = SearchOptions(
            query="team",
            fields=["summary", "description", "location"],
            case_sensitive=False,
        )

        results = search_events_func(events, opts)
        assert len(results) == 3  # Team Meeting, team sync, Team lunch

        # Case sensitive
        opts_case = SearchOptions(
            query="team",
            fields=["summary", "description", "location"],
            case_sensitive=True,
        )
        results_case = search_events_func(events, opts_case)
        assert len(results_case) == 2  # Only lowercase 'team' matches

    def test_field_specific_search(self):
        """Test searching specific fields"""
        events = self.create_test_events()

        # Search only in summary
        opts = SearchOptions(query="team", fields=["summary"])
        results = search_events_func(events, opts)
        assert len(results) == 1  # Only "Team Meeting"

        # Search only in location
        opts = SearchOptions(query="room", fields=["location"])
        results = search_events_func(events, opts)
        assert len(results) == 2  # Conference Room A, Meeting Room B

    def test_match_type_search(self):
        """Test different match types"""
        events = self.create_test_events()

        # Starts with
        opts = SearchOptions(
            query="team",
            fields=["summary", "description", "location"],
            match_type="starts_with",
        )
        results = search_events_func(events, opts)
        assert len(results) == 2  # Team Meeting, Team lunch

        # Ends with
        opts = SearchOptions(
            query="call",
            fields=["summary", "description", "location"],
            match_type="ends_with",
        )
        results = search_events_func(events, opts)
        assert len(results) == 1  # Client Call

        # Exact match
        opts = SearchOptions(
            query="Lunch Break",
            fields=["summary", "description", "location"],
            match_type="exact",
        )
        results = search_events_func(events, opts)
        assert len(results) == 1
        assert results[0]["uid"] == "4"

    def test_date_range_search(self):
        """Test date range filtering"""
        events = self.create_test_events()
        base_date = datetime.now()

        # Future events only (including today)
        opts = SearchOptions(
            query="",  # No text filter
            fields=["summary", "description", "location"],
            date_start=base_date - timedelta(seconds=1),  # Slightly before to include "today"
            date_end=base_date + timedelta(days=7),
        )
        results = search_events_func(events, opts)
        assert len(results) == 3  # Today's lunch + 2 future events

        # Past events only
        opts = SearchOptions(
            query="",
            fields=["summary", "description", "location"],
            date_start=base_date - timedelta(days=7),
            date_end=base_date - timedelta(hours=1),
        )
        results = search_events_func(events, opts)
        assert len(results) == 1  # Yesterday's team meeting

    def test_combined_text_and_date_search(self):
        """Test combining text and date filters"""
        events = self.create_test_events()
        base_date = datetime.now()

        opts = SearchOptions(
            query="meeting",
            fields=["summary", "description", "location"],
            date_start=base_date,
            date_end=base_date + timedelta(days=7),
        )
        results = search_events_func(events, opts)
        assert len(results) == 1  # Only future meeting (Meeting Room B)
        assert results[0]["uid"] == "3"

    def test_regex_search(self):
        """Test regex pattern search"""
        events = self.create_test_events()

        # Match "Room" followed by a letter
        opts = SearchOptions(
            query=r"Room\s+[A-Z]",
            fields=["summary", "description", "location"],
            use_regex=True,
        )
        results = search_events_func(events, opts)
        assert len(results) == 2  # Conference Room A, Meeting Room B

        # Match events with numbers
        events[0]["summary"] = "Team Meeting #123"
        opts = SearchOptions(
            query=r"#\d+", fields=["summary", "description", "location"], use_regex=True
        )
        results = search_events_func(events, opts)
        assert len(results) == 1
        assert results[0]["uid"] == "1"

    def test_max_results_limiting(self):
        """Test result limiting"""
        events = self.create_test_events()

        opts = SearchOptions(
            query="e", fields=["summary", "description", "location"], max_results=2
        )  # Matches all events
        results = search_events_func(events, opts)
        assert len(results) == 2  # Limited to 2 results


class TestRelevanceScoring:
    def test_field_weight_scoring(self):
        """Test that different fields have different weights"""
        opts = SearchOptions(query="important", fields=["summary", "description", "location"])

        # Event with match in summary (weight 3.0)
        event_summary = {
            "summary": "Important Meeting",
            "description": "Regular meeting",
            "location": "Room A",
        }

        # Event with match in description (weight 2.0)
        event_desc = {
            "summary": "Regular Meeting",
            "description": "Important topics to discuss",
            "location": "Room B",
        }

        # Event with match in location (weight 1.0)
        event_loc = {
            "summary": "Regular Meeting",
            "description": "Weekly sync",
            "location": "Important Building",
        }

        score_summary = calculate_relevance_score(event_summary, opts)
        score_desc = calculate_relevance_score(event_desc, opts)
        score_loc = calculate_relevance_score(event_loc, opts)

        assert score_summary > score_desc > score_loc

    def test_position_scoring(self):
        """Test that earlier matches score higher"""
        opts = SearchOptions(query="meeting", fields=["summary", "description", "location"])

        # Match at beginning
        event_start = {
            "summary": "Meeting with client",
            "description": "",
            "location": "",
        }

        # Match at end
        event_end = {
            "summary": "Client discussion meeting",
            "description": "",
            "location": "",
        }

        score_start = calculate_relevance_score(event_start, opts)
        score_end = calculate_relevance_score(event_end, opts)

        assert score_start > score_end

    def test_recency_scoring(self):
        """Test that recent events get a boost"""
        opts = SearchOptions(query="meeting", fields=["summary", "description", "location"])
        current_time = datetime.now()

        # Event from today
        event_today = {"summary": "Team Meeting", "dtstart": current_time}

        # Event from 20 days ago
        event_old = {
            "summary": "Team Meeting",
            "dtstart": current_time - timedelta(days=20),
        }

        score_today = calculate_relevance_score(event_today, opts, current_time)
        score_old = calculate_relevance_score(event_old, opts, current_time)

        assert score_today > score_old

    def test_search_events_ranked(self):
        """Test ranked search results"""
        events = [
            {
                "uid": "1",
                "summary": "Important Team Meeting",
                "description": "",
                "location": "",
            },
            {
                "uid": "2",
                "summary": "Meeting",
                "description": "Important topics",
                "location": "",
            },
            {
                "uid": "3",
                "summary": "Lunch",
                "description": "",
                "location": "Meeting Room",
            },
            {
                "uid": "4",
                "summary": "Team Meeting Tomorrow",
                "description": "",
                "location": "",
            },
        ]

        opts = SearchOptions(query="meeting", fields=["summary", "description", "location"])
        ranked_results = search_events_ranked(events, opts)

        assert len(ranked_results) == 4
        assert all(isinstance(r[1], float) for r in ranked_results)  # All have scores

        # First result should have highest score
        assert ranked_results[0][1] > ranked_results[-1][1]

        # Check that it found the right events
        uids = [r[0]["uid"] for r in ranked_results]
        assert "1" in uids  # Has "Meeting" in summary
        assert "2" in uids  # Has "Meeting" in summary
        assert "3" in uids  # Has "Meeting" in location
        assert "4" in uids  # Has "Meeting" in summary
