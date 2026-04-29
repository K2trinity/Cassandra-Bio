from __future__ import annotations

import re
from typing import Callable

import requests


DATA_INSUFFICIENT = "数据不足"

KNOWN_COMPANY_PIPELINE_URLS = {
    "eisai": "https://www.eisai.com/innovation/research/pipeline/index.html",
    "biogen": "https://www.biogen.com/science-and-innovation/pipeline.html",
    "eli-lilly": "https://www.lilly.com/discovery/clinical-development-pipeline",
    "lilly": "https://www.lilly.com/discovery/clinical-development-pipeline",
    "roche": "https://www.roche.com/solutions/pipeline",
    "hoffmann-la-roche": "https://www.roche.com/solutions/pipeline",
    "novartis": "https://www.novartis.com/research-development/novartis-pipeline",
    "astrazeneca": "https://www.astrazeneca.com/our-therapy-areas/pipeline.html",
    "gsk": "https://www.gsk.com/en-gb/innovation/pipeline/",
    "glaxosmithkline": "https://www.gsk.com/en-gb/innovation/pipeline/",
    "sanofi": "https://www.sanofi.com/en/our-science/our-pipeline",
    "regeneron": "https://www.regeneron.com/science/investigational-pipeline",
    "regeneron-pharmaceuticals": "https://www.regeneron.com/science/investigational-pipeline",
    "teva": "https://www.tevapharm.com/science/pipeline/",
    "teva-branded-pharmaceutical-products-r-d": "https://www.tevapharm.com/science/pipeline/",
    "amgen": "https://www.amgenpipeline.com/",
    "merck": "https://www.merck.com/research/product-pipeline/",
    "pfizer": "https://www.pfizer.com/science/drug-product-pipeline",
    "takeda": "https://www.takeda.com/science/pipeline/",
}


class CompanyApproachClient:
    def __init__(
        self,
        fetch_text: Callable[[str], str] | None = None,
        company_urls: dict[str, str] | None = None,
    ):
        self.fetch_text = fetch_text or self._default_fetch_text
        url_map = KNOWN_COMPANY_PIPELINE_URLS if company_urls is None else company_urls
        self.company_urls = {
            self._slugify(company): url
            for company, url in url_map.items()
        }

    def fetch_company_route(
        self,
        company_name,
        representative_assets,
        targets,
        modality,
    ) -> dict:
        assets = list(representative_assets or [])
        target_list = list(targets or [])
        url = self._build_pipeline_url(company_name)

        if not url:
            return self._data_insufficient_result(company_name, assets, target_list, modality)

        text = self.fetch_text(url)
        if not text:
            return self._data_insufficient_result(company_name, assets, target_list, modality)

        route_terms = self._extract_route_terms(text, target_list, modality)
        route_summary = self._summarize_route(company_name, assets, route_terms, text)
        slug = self._slugify(company_name)

        return {
            "company_name": company_name,
            "company": company_name,
            "representative_assets": assets,
            "lead_asset": assets[0] if assets else DATA_INSUFFICIENT,
            "technical_route": route_terms or DATA_INSUFFICIENT,
            "route": route_terms or DATA_INSUFFICIENT,
            "targets": target_list,
            "modality": modality or DATA_INSUFFICIENT,
            "route_summary": route_summary or DATA_INSUFFICIENT,
            "evidence": route_summary or DATA_INSUFFICIENT,
            "why_it_fits_disease": DATA_INSUFFICIENT,
            "evidence_ids": [f"ev_company_{slug}_pipeline"] if route_terms else [],
            "source_url": url,
            "status": "matched" if route_terms else "no_match",
        }

    def _build_pipeline_url(self, company_name) -> str:
        slug = self._slugify(company_name)
        if slug in self.company_urls:
            return self.company_urls[slug]
        base_slug = self._company_base_slug(company_name)
        for candidate_slug, url in self.company_urls.items():
            if candidate_slug == base_slug or self._company_base_slug(candidate_slug) == base_slug:
                return url
        return ""

    def _default_fetch_text(self, url) -> str:
        try:
            response = requests.get(url, timeout=8)
        except requests.RequestException:
            return ""

        if response.status_code >= 400:
            return ""
        return response.text[:50000]

    def _extract_route_terms(self, text, targets, modality) -> str:
        normalized_text = self._normalize_beta(text).lower()
        matched_targets = []
        for target in targets or []:
            target_text = str(target).strip()
            if not target_text:
                continue
            if self._normalize_beta(target_text).lower() in normalized_text:
                matched_targets.append(target_text)

        route_parts = list(matched_targets)
        if modality and str(modality).strip().lower() in normalized_text:
            route_parts.append(str(modality).strip())

        if not route_parts:
            route_parts = [
                str(target).strip()
                for target in (targets or [])
                if str(target).strip()
            ]
            if modality and str(modality).strip():
                route_parts.append(str(modality).strip())

        return " ".join(route_parts)

    def _summarize_route(self, company_name, assets, route_terms, text) -> str:
        if not route_terms:
            return DATA_INSUFFICIENT

        asset_text = ", ".join(str(asset) for asset in assets if str(asset).strip())
        if asset_text:
            return f"{company_name} pipeline text links {asset_text} to {route_terms}."
        return f"{company_name} pipeline text supports {route_terms}."

    def _data_insufficient_result(self, company_name, assets, targets, modality) -> dict:
        return {
            "company_name": company_name,
            "company": company_name,
            "representative_assets": assets,
            "lead_asset": assets[0] if assets else DATA_INSUFFICIENT,
            "technical_route": DATA_INSUFFICIENT,
            "route": DATA_INSUFFICIENT,
            "targets": targets,
            "modality": modality or DATA_INSUFFICIENT,
            "route_summary": DATA_INSUFFICIENT,
            "evidence": DATA_INSUFFICIENT,
            "why_it_fits_disease": DATA_INSUFFICIENT,
            "evidence_ids": [],
            "source_url": "",
            "status": "data_insufficient",
        }

    @staticmethod
    def _slugify(value) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
        return slug

    @staticmethod
    def _company_base_slug(value) -> str:
        suffixes = {
            "inc",
            "ltd",
            "llc",
            "corp",
            "corporation",
            "company",
            "co",
            "limited",
            "pharmaceutical",
            "pharmaceuticals",
            "plc",
            "sa",
            "ag",
            "gmbh",
        }
        tokens = [
            token
            for token in re.split(r"[^a-z0-9]+", str(value or "").lower())
            if token and token not in suffixes and token != "and"
        ]
        return CompanyApproachClient._slugify(" ".join(tokens))

    @staticmethod
    def _normalize_beta(value) -> str:
        return (
            str(value or "")
            .replace("Aβ", "amyloid beta")
            .replace("aβ", "amyloid beta")
            .replace("AΒ", "amyloid beta")
            .replace("aΒ", "amyloid beta")
        )
