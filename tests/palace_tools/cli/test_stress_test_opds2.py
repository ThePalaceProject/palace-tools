"""Tests for stress_test_opds2 CLI tool."""

from __future__ import annotations

from palace_tools.cli.stress_test_opds2 import (
    RequestResult,
    StressTestStats,
    get_next_url,
)


class TestRequestResult:
    """Tests for RequestResult dataclass."""

    def test_success_with_200_status(self) -> None:
        result = RequestResult(
            url="http://example.com/feed",
            status_code=200,
            response_time=0.5,
        )
        assert result.success is True

    def test_failure_with_non_200_status(self) -> None:
        for status_code in [400, 401, 403, 404, 500, 502, 503]:
            result = RequestResult(
                url="http://example.com/feed",
                status_code=status_code,
                response_time=0.5,
            )
            assert result.success is False

    def test_optional_fields_default_to_none(self) -> None:
        result = RequestResult(
            url="http://example.com/feed",
            status_code=200,
            response_time=0.5,
        )
        assert result.response_headers is None
        assert result.response_body is None

    def test_with_headers_and_body(self) -> None:
        result = RequestResult(
            url="http://example.com/feed",
            status_code=200,
            response_time=0.5,
            response_headers={"Content-Type": "application/json"},
            response_body='{"test": "data"}',
        )
        assert result.response_headers == {"Content-Type": "application/json"}
        assert result.response_body == '{"test": "data"}'


class TestStressTestStats:
    """Tests for StressTestStats dataclass."""

    def test_empty_stats(self) -> None:
        stats = StressTestStats()
        assert stats.total_requests() == 0
        assert stats.successful_requests() == 0
        assert stats.failed_requests() == 0
        assert stats.success_response_times() == []
        assert stats.error_response_times() == []
        assert stats.failed_results() == []
        assert stats.failures_by_status() == {}

    def test_add_successful_result(self) -> None:
        stats = StressTestStats()
        result = RequestResult(
            url="http://example.com/feed",
            status_code=200,
            response_time=0.5,
        )
        stats.add_result(result)

        assert stats.total_requests() == 1
        assert stats.successful_requests() == 1
        assert stats.failed_requests() == 0
        assert stats.success_response_times() == [0.5]
        assert stats.error_response_times() == []

    def test_add_failed_result(self) -> None:
        stats = StressTestStats()
        result = RequestResult(
            url="http://example.com/feed",
            status_code=500,
            response_time=1.0,
        )
        stats.add_result(result)

        assert stats.total_requests() == 1
        assert stats.successful_requests() == 0
        assert stats.failed_requests() == 1
        assert stats.success_response_times() == []
        assert stats.error_response_times() == [1.0]
        assert stats.failed_results() == [result]

    def test_mixed_results(self) -> None:
        stats = StressTestStats()
        stats.add_result(
            RequestResult(
                url="http://example.com/1", status_code=200, response_time=0.1
            )
        )
        stats.add_result(
            RequestResult(
                url="http://example.com/2", status_code=200, response_time=0.2
            )
        )
        stats.add_result(
            RequestResult(
                url="http://example.com/3", status_code=500, response_time=0.3
            )
        )
        stats.add_result(
            RequestResult(
                url="http://example.com/4", status_code=404, response_time=0.4
            )
        )

        assert stats.total_requests() == 4
        assert stats.successful_requests() == 2
        assert stats.failed_requests() == 2
        assert stats.success_response_times() == [0.1, 0.2]
        assert stats.error_response_times() == [0.3, 0.4]

    def test_failures_by_status(self) -> None:
        stats = StressTestStats()
        stats.add_result(
            RequestResult(
                url="http://example.com/1", status_code=500, response_time=0.1
            )
        )
        stats.add_result(
            RequestResult(
                url="http://example.com/2", status_code=500, response_time=0.2
            )
        )
        stats.add_result(
            RequestResult(
                url="http://example.com/3", status_code=404, response_time=0.3
            )
        )
        stats.add_result(
            RequestResult(
                url="http://example.com/4", status_code=200, response_time=0.4
            )
        )

        failures = stats.failures_by_status()
        assert failures == {500: 2, 404: 1}

    def test_total_duration(self) -> None:
        stats = StressTestStats()
        stats.start_time = 100.0
        stats.end_time = 110.5

        assert stats.total_duration() == 10.5

    def test_full_harvests_counter(self) -> None:
        stats = StressTestStats()
        assert stats.full_harvests == 0

        stats.full_harvests += 1
        assert stats.full_harvests == 1


class TestGetNextUrl:
    """Tests for get_next_url function."""

    def test_with_next_link_string_rel(self) -> None:
        response_data = {
            "links": [
                {"rel": "self", "href": "http://example.com/feed?page=1"},
                {"rel": "next", "href": "http://example.com/feed?page=2"},
            ]
        }
        assert get_next_url(response_data) == "http://example.com/feed?page=2"

    def test_with_next_link_list_rel(self) -> None:
        response_data = {
            "links": [
                {"rel": ["self"], "href": "http://example.com/feed?page=1"},
                {
                    "rel": ["next", "http://opds-spec.org/sort/new"],
                    "href": "http://example.com/feed?page=2",
                },
            ]
        }
        assert get_next_url(response_data) == "http://example.com/feed?page=2"

    def test_without_next_link(self) -> None:
        response_data = {
            "links": [
                {"rel": "self", "href": "http://example.com/feed?page=1"},
                {"rel": "first", "href": "http://example.com/feed?page=1"},
            ]
        }
        assert get_next_url(response_data) is None

    def test_empty_links(self) -> None:
        response_data: dict[str, list[dict[str, str]]] = {"links": []}
        assert get_next_url(response_data) is None

    def test_no_links_key(self) -> None:
        response_data: dict[str, str] = {"metadata": "test"}
        assert get_next_url(response_data) is None

    def test_link_without_href(self) -> None:
        response_data = {
            "links": [
                {"rel": "next"},
            ]
        }
        assert get_next_url(response_data) is None

    def test_link_with_non_string_href(self) -> None:
        response_data = {
            "links": [
                {"rel": "next", "href": 123},
            ]
        }
        assert get_next_url(response_data) is None
