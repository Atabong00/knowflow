from app.core.config import settings


class PerformanceConfig:
    """Configurable performance classification thresholds (section 14).

    Thresholds can be overridden via environment variables so they are not
    hard-coded throughout the application.
    """

    _thresholds = None

    @classmethod
    def thresholds(cls):
        if cls._thresholds is None:
            cls._thresholds = {
                "excellent_min": int(getattr(settings, "PERF_EXCELLENT_MIN", "90")),
                "very_good_min": int(getattr(settings, "PERF_VERY_GOOD_MIN", "80")),
                "good_min": int(getattr(settings, "PERF_GOOD_MIN", "70")),
                "needs_improvement_min": int(getattr(settings, "PERF_NEEDS_IMPROVEMENT_MIN", "50")),
            }
        return cls._thresholds

    @classmethod
    def classify(cls, percentage: int) -> tuple[str, str]:
        """Return (performance_label, css_key) for a given percentage."""
        t = cls.thresholds()
        if percentage >= t["excellent_min"]:
            return ("Excellent", "excellent")
        elif percentage >= t["very_good_min"]:
            return ("Very Good", "very_good")
        elif percentage >= t["good_min"]:
            return ("Good / Passed", "good")
        elif percentage >= t["needs_improvement_min"]:
            return ("Needs Improvement", "needs_improvement")
        else:
            return ("Poor", "poor")
