"""Tests for stress_test_opds2 CLI tool."""

from __future__ import annotations

from palace_tools.cli.stress_test_opds2 import (
    RequestResult,
    ResponseTimeStats,
    StressTestStats,
    get_next_url,
)


class TestRequestResult:
    """Tests for RequestResult dataclass."""

    def test_success_field(self) -> None:
        success_result = RequestResult(
            url="http://example.com/feed",
            status_code=200,
            response_time=0.5,
            success=True,
        )
        assert success_result.success is True

        failure_result = RequestResult(
            url="http://example.com/feed",
            status_code=500,
            response_time=0.5,
            success=False,
        )
        assert failure_result.success is False

    def test_optional_fields_default_to_none(self) -> None:
        result = RequestResult(
            url="http://example.com/feed",
            status_code=200,
            response_time=0.5,
            success=True,
        )
        assert result.response_headers is None
        assert result.response_body is None

    def test_with_headers_and_body(self) -> None:
        result = RequestResult(
            url="http://example.com/feed",
            status_code=500,
            response_time=0.5,
            success=False,
            response_headers={"Content-Type": "application/json"},
            response_body='{"error": "data"}',
        )
        assert result.response_headers == {"Content-Type": "application/json"}
        assert result.response_body == '{"error": "data"}'


class TestStressTestStats:
    """Tests for StressTestStats dataclass."""

    def test_empty_stats(self) -> None:
        stats = StressTestStats()
        assert stats.total_requests() == 0
        assert stats.successful_requests() == 0
        assert stats.failed_requests() == 0
        assert stats.success_response_times().count == 0
        assert stats.error_response_times().count == 0
        assert len(stats.failed_results()) == 0
        assert stats.failures_by_status() == {}

    def test_add_successful_result(self) -> None:
        stats = StressTestStats()
        result = RequestResult(
            url="http://example.com/feed",
            status_code=200,
            response_time=0.5,
            success=True,
        )
        stats.add_result(result)

        assert stats.total_requests() == 1
        assert stats.successful_requests() == 1
        assert stats.failed_requests() == 0
        success_times = stats.success_response_times()
        assert success_times.count == 1
        assert success_times.avg == 0.5
        assert success_times.min_val == 0.5
        assert success_times.max_val == 0.5
        assert stats.error_response_times().count == 0

    def test_add_failed_result(self) -> None:
        stats = StressTestStats()
        result = RequestResult(
            url="http://example.com/feed",
            status_code=500,
            response_time=1.0,
            success=False,
        )
        stats.add_result(result)

        assert stats.total_requests() == 1
        assert stats.successful_requests() == 0
        assert stats.failed_requests() == 1
        assert stats.success_response_times().count == 0
        error_times = stats.error_response_times()
        assert error_times.count == 1
        assert error_times.avg == 1.0
        assert error_times.min_val == 1.0
        assert error_times.max_val == 1.0
        assert list(stats.failed_results()) == [result]

    def test_mixed_results(self) -> None:
        stats = StressTestStats()
        stats.add_result(
            RequestResult(
                url="http://example.com/1",
                status_code=200,
                response_time=0.1,
                success=True,
            )
        )
        stats.add_result(
            RequestResult(
                url="http://example.com/2",
                status_code=200,
                response_time=0.2,
                success=True,
            )
        )
        stats.add_result(
            RequestResult(
                url="http://example.com/3",
                status_code=500,
                response_time=0.3,
                success=False,
            )
        )
        stats.add_result(
            RequestResult(
                url="http://example.com/4",
                status_code=404,
                response_time=0.4,
                success=False,
            )
        )

        assert stats.total_requests() == 4
        assert stats.successful_requests() == 2
        assert stats.failed_requests() == 2
        success_times = stats.success_response_times()
        assert success_times.count == 2
        assert success_times.min_val == 0.1
        assert success_times.max_val == 0.2
        error_times = stats.error_response_times()
        assert error_times.count == 2
        assert error_times.min_val == 0.3
        assert error_times.max_val == 0.4

    def test_failures_by_status(self) -> None:
        stats = StressTestStats()
        stats.add_result(
            RequestResult(
                url="http://example.com/1",
                status_code=500,
                response_time=0.1,
                success=False,
            )
        )
        stats.add_result(
            RequestResult(
                url="http://example.com/2",
                status_code=500,
                response_time=0.2,
                success=False,
            )
        )
        stats.add_result(
            RequestResult(
                url="http://example.com/3",
                status_code=404,
                response_time=0.3,
                success=False,
            )
        )
        stats.add_result(
            RequestResult(
                url="http://example.com/4",
                status_code=200,
                response_time=0.4,
                success=True,
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

    def test_recent_failures_limit(self) -> None:
        """Test that only the most recent failures are kept to limit memory usage."""
        stats = StressTestStats(max_recent_failures=5)

        # Add more failures than the limit
        for i in range(10):
            stats.add_result(
                RequestResult(
                    url=f"http://example.com/{i}",
                    status_code=500,
                    response_time=0.1,
                    success=False,
                )
            )

        # Should have all 10 counted but only 5 stored
        assert stats.failed_requests() == 10
        assert len(stats.failed_results()) == 5
        # Should keep the most recent failures (5-9), not the first ones (0-4)
        urls = [r.url for r in stats.failed_results()]
        assert urls == [f"http://example.com/{i}" for i in range(5, 10)]


class TestResponseTimeStats:
    """Tests for ResponseTimeStats class."""

    def test_empty_stats(self) -> None:
        stats = ResponseTimeStats()
        assert stats.count == 0
        assert stats.avg == 0.0
        assert stats.min_val == float("inf")
        assert stats.max_val == float("-inf")
        assert stats.percentile(50) is None
        assert stats.percentile(99) is None

    def test_single_value(self) -> None:
        stats = ResponseTimeStats()
        stats.add(5.0)
        assert stats.count == 1
        assert stats.avg == 5.0
        assert stats.min_val == 5.0
        assert stats.max_val == 5.0
        # With a single value, percentiles should be approximately that value
        # (DDSketch uses approximation with 1% relative error)
        median = stats.percentile(50)
        assert median is not None
        assert 4.95 <= median <= 5.05
        p99 = stats.percentile(99)
        assert p99 is not None
        assert 4.95 <= p99 <= 5.05

    def test_multiple_values(self) -> None:
        stats = ResponseTimeStats()
        stats.add(1.0)
        stats.add(2.0)
        stats.add(3.0)
        assert stats.count == 3
        assert stats.avg == 2.0
        assert stats.min_val == 1.0
        assert stats.max_val == 3.0

    def test_percentiles_with_many_values(self) -> None:
        """Test percentile accuracy with enough data points."""
        stats = ResponseTimeStats()
        # Add 100 values from 1 to 100
        for i in range(1, 101):
            stats.add(float(i))

        assert stats.count == 100
        assert stats.min_val == 1.0
        assert stats.max_val == 100.0

        # Check percentiles are approximately correct (within 1% relative error)
        median = stats.percentile(50)
        assert median is not None
        assert 49.5 <= median <= 51.5  # Should be around 50

        p99 = stats.percentile(99)
        assert p99 is not None
        assert 98.0 <= p99 <= 100.0  # Should be around 99

    def test_histogram_empty(self) -> None:
        """Test histogram returns empty list for empty stats."""
        stats = ResponseTimeStats()
        assert stats.histogram() == []

    def test_histogram_single_value(self) -> None:
        """Test histogram with single value returns one bucket."""
        stats = ResponseTimeStats()
        stats.add(5.0)
        histogram = stats.histogram()
        assert len(histogram) == 1
        assert histogram[0] == (5.0, 5.0, 1)

    def test_histogram_with_data(self) -> None:
        """Test histogram with fixed-width buckets shows distribution."""
        stats = ResponseTimeStats()
        # Add values clustered at the low end: many small, few large
        for _ in range(80):
            stats.add(1.0)  # 80 values at 1.0
        for _ in range(20):
            stats.add(10.0)  # 20 values at 10.0

        histogram = stats.histogram(num_buckets=10)
        assert len(histogram) == 10

        # Total count should approximately equal input count
        total_count = sum(count for _, _, count in histogram)
        assert 95 <= total_count <= 105  # Allow some approximation error

        # First bucket (1.0-1.9) should have most values
        # Last bucket (9.1-10.0) should have some values
        # Middle buckets should be mostly empty
        first_bucket_count = histogram[0][2]
        last_bucket_count = histogram[-1][2]
        middle_counts = sum(count for _, _, count in histogram[1:-1])

        assert first_bucket_count > middle_counts  # Most values in first bucket
        assert last_bucket_count > 0  # Some values in last bucket

        # Buckets should have fixed width and be contiguous
        bucket_width = histogram[0][1] - histogram[0][0]
        for i, (start, end, _) in enumerate(histogram):
            expected_start = 1.0 + (i * bucket_width)
            assert abs(start - expected_start) < 0.01
            assert abs(end - start - bucket_width) < 0.01

    def test_merge(self) -> None:
        """Test merging two ResponseTimeStats (mutates self)."""
        stats1 = ResponseTimeStats()
        stats1.add(1.0)
        stats1.add(2.0)

        stats2 = ResponseTimeStats()
        stats2.add(3.0)
        stats2.add(4.0)

        stats1.merge(stats2)

        assert stats1.count == 4
        assert stats1.avg == 2.5
        assert stats1.min_val == 1.0
        assert stats1.max_val == 4.0

    def test_merge_empty(self) -> None:
        """Test merging with empty stats."""
        stats1 = ResponseTimeStats()
        stats1.add(1.0)

        stats2 = ResponseTimeStats()

        stats1.merge(stats2)
        assert stats1.count == 1
        assert stats1.min_val == 1.0


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
