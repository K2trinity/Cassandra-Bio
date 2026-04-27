from __future__ import annotations

from typing import Protocol

from .models import DiseaseReportPackage


class CompanyRouteProvider(Protocol):
    """Dormant extension point for company-route enrichment."""

    def enrich(self, package: DiseaseReportPackage) -> DiseaseReportPackage:
        """Return a disease report package with any route enrichment applied."""


class NoopCompanyRouteProvider:
    """Default provider that leaves the disease report package unchanged."""

    def enrich(self, package: DiseaseReportPackage) -> DiseaseReportPackage:
        return package


__all__ = ["CompanyRouteProvider", "NoopCompanyRouteProvider"]
