"""Independent selection reports sharing one crawl over the union of date ranges."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from core.analyzer import ProductAnalyzer
from core.models import OccurrenceFilterConfig, RetainedProduct, TimeFilterConfig
from core.record_identity import deduplicate_items, sanitize_items

REPORT_LABELS = {
    "likes": "按点赞量",
    "total": "按总频次",
    "accounts": "按跨账号数",
    "both": "按账号及频次",
}


@dataclass
class ReportTask:
    time_config: TimeFilterConfig = field(default_factory=TimeFilterConfig)
    filter_config: OccurrenceFilterConfig = field(
        default_factory=OccurrenceFilterConfig
    )

    @property
    def name(self) -> str:
        return REPORT_LABELS[self.filter_config.filter_by]

    def to_dict(self) -> dict:
        return {
            "time_config": vars(self.time_config),
            "filter_config": vars(self.filter_config),
        }

    @classmethod
    def from_dict(cls, value: dict) -> ReportTask:
        if not isinstance(value, dict):
            raise ValueError("报表任务格式无效")
        time = value.get("time_config") or {}
        filters = value.get("filter_config") or {}
        mode = filters.get("filter_by", "accounts")
        if mode not in REPORT_LABELS:
            raise ValueError("报表筛选条件无效")
        time_config = TimeFilterConfig(
            **{
                key: time[key]
                for key in ("mode", "days", "start_date", "end_date")
                if key in time
            }
        )
        if (
            time_config.mode not in ("days", "range", "all")
            or int(time_config.days) < 1
        ):
            raise ValueError("报表时间范围无效")
        time_config.days = int(time_config.days)
        start, end = time_config.get_timestamps()
        if start is not None and end is not None and start > end:
            raise ValueError("报表起始日期晚于结束日期")
        config = OccurrenceFilterConfig(
            **{
                key: filters[key]
                for key in vars(OccurrenceFilterConfig())
                if key in filters
            }
        )
        config.min_account_count = max(1, int(config.min_account_count))
        config.min_total_occurrences = max(1, int(config.min_total_occurrences))
        config.min_like_count = max(0, int(config.min_like_count))
        config.fuzzy_threshold = max(0.0, min(1.0, float(config.fuzzy_threshold)))
        return cls(time_config, config)


@dataclass
class SelectionReport:
    task: ReportTask
    products: list[RetainedProduct]
    items: list

    def to_dict(self) -> dict:
        return {
            "name": self.task.name,
            "filter_by": self.task.filter_config.filter_by,
            **self.task.to_dict(),
            "retained_products": [p.to_summary_dict() for p in self.products],
        }


def crawl_time_filter(
    tasks: list[ReportTask], now: datetime | None = None
) -> TimeFilterConfig:
    """Do not stop crawling before any selected report's date range is covered."""
    if len(tasks) == 1 and tasks[0].time_config.mode != "days":
        return tasks[0].time_config
    bounds = [task.time_config.get_timestamps(now) for task in tasks]
    starts = [start for start, _ in bounds]
    ends = [end for _, end in bounds]
    return TimeFilterConfig(
        mode="range",
        start_date=datetime.fromtimestamp(min(starts)).date().isoformat()
        if all(value is not None for value in starts)
        else "",
        end_date=datetime.fromtimestamp(max(ends)).date().isoformat()
        if all(value is not None for value in ends)
        else "",
    )


def analyze_reports(
    items, tasks: list[ReportTask], *, now=None, on_issue=None
) -> list[SelectionReport]:
    observations = deduplicate_items(sanitize_items(items, on_issue))
    reports = []
    for task in tasks:
        start, end = task.time_config.get_timestamps(now)
        selected = []
        for item in observations:
            timestamp = item.publish_time
            if not timestamp and item.publish_time_str:
                try:
                    timestamp = datetime.fromisoformat(
                        item.publish_time_str
                    ).timestamp()
                except (ValueError, OverflowError, OSError):
                    pass
            if (start is not None or end is not None) and not timestamp:
                continue
            if (
                start is not None
                and timestamp < start
                or end is not None
                and timestamp > end
            ):
                continue
            selected.append(item)
        retained, _ = ProductAnalyzer(task.filter_config).aggregate_and_filter(selected, include_unfiltered=False)
        reports.append(SelectionReport(task, retained, selected))
    return reports
