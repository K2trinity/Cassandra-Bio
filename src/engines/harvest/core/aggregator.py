"""Data aggregation logic without IO side effects."""

from typing import Any, Dict, List

from ..schemas import DataCandidate


def aggregate_data(pubmed_articles: List[Dict[str, Any]], trials: List[Dict[str, Any]]) -> List[DataCandidate]:
    """Convert raw source payloads into a unified typed data list."""
    data_candidates: List[DataCandidate] = []

    for article in pubmed_articles:
        is_europmc = article.get("source") == "EuroPMC"
        data_candidates.append(
            DataCandidate(
                title=article.get("title", "No title"),
                source="EuroPMC" if is_europmc else "PubMed",
                snippet=article.get("abstract", "")[:500] + "...",
                link=article.get("pubmed_link", ""),
                status="Published",
                date=article.get("pub_date", "Unknown"),
                metadata={
                    "pmid": article.get("pmid"),
                    "pmcid": article.get("pmcid"),
                    "authors": article.get("authors"),
                    "journal": article.get("journal"),
                    "doi": article.get("doi"),
                    "pmc_link": article.get("pmc_link"),
                    "pdf_url": article.get("pdf_url"),
                },
            )
        )

    for trial in trials:
        nct_id = trial.get("nct_id")
        trial_metadata = {
            "nct_number": trial.get("nct_number", nct_id),
            "nct_id": nct_id,
            "study_url": trial.get("study_url", trial.get("url", "")),
            "url": trial.get("url", ""),
            "acronym": trial.get("acronym", "N/A"),
            "study_status": trial.get("study_status", trial.get("status", "N/A")),
            "brief_summary": trial.get("brief_summary", "N/A"),
            "has_results": trial.get("has_results", "False"),
            "study_results": trial.get("study_results", "No posted results"),
            "results_url": trial.get("results_url", ""),
            "phases": trial.get("phases", trial.get("phase", "N/A")),
            "phase": trial.get("phase"),
            "study_design": trial.get("study_design", "N/A"),
            "why_stopped": trial.get("why_stopped", "N/A"),
            "interventions": trial.get("interventions"),
            "conditions": trial.get("conditions"),
            "primary_outcome_measures": trial.get("primary_outcome_measures", "Not specified"),
            "secondary_outcome_measures": trial.get("secondary_outcome_measures", "Not specified"),
            "other_outcome_measures": trial.get("other_outcome_measures", "Not specified"),
            "sponsor": trial.get("sponsor"),
            "collaborators": trial.get("collaborators", "None"),
            "funder_type": trial.get("funder_type", "N/A"),
            "sex": trial.get("sex", "N/A"),
            "age": trial.get("age", "N/A"),
            "enrollment": trial.get("enrollment"),
            "study_type": trial.get("study_type", "N/A"),
            "other_ids": trial.get("other_ids", "N/A"),
            "start_date": trial.get("start_date"),
            "primary_completion_date": trial.get("primary_completion_date", "N/A"),
            "completion_date": trial.get("completion_date"),
            "first_posted": trial.get("first_posted", "N/A"),
            "results_first_posted": trial.get("results_first_posted", "N/A"),
            "last_update_posted": trial.get("last_update_posted", "N/A"),
            "study_documents": trial.get("study_documents", "None"),
        }

        data_candidates.append(
            DataCandidate(
                title=trial.get("title", "No title"),
                source="ClinicalTrials.gov",
                snippet=trial.get("brief_summary", "Summary not provided"),
                link=trial.get("url", ""),
                status=trial.get("status", "UNKNOWN"),
                date=trial.get("completion_date", "Unknown"),
                nct_number=trial.get("nct_number", nct_id),
                nct_id=nct_id,
                study_url=trial.get("study_url", trial.get("url", "")),
                url=trial.get("url", ""),
                acronym=trial.get("acronym", "N/A"),
                study_status=trial.get("study_status", trial.get("status", "N/A")),
                brief_summary=trial.get("brief_summary", "N/A"),
                has_results=trial.get("has_results", "False"),
                study_results=trial.get("study_results", "No posted results"),
                results_url=trial.get("results_url", ""),
                phases=trial.get("phases", trial.get("phase", "N/A")),
                phase=trial.get("phase", "N/A"),
                study_design=trial.get("study_design", "N/A"),
                why_stopped=trial.get("why_stopped", "N/A"),
                interventions=trial.get("interventions", "N/A"),
                conditions=trial.get("conditions", "N/A"),
                primary_outcome_measures=trial.get("primary_outcome_measures", "Not specified"),
                secondary_outcome_measures=trial.get("secondary_outcome_measures", "Not specified"),
                other_outcome_measures=trial.get("other_outcome_measures", "Not specified"),
                sponsor=trial.get("sponsor", "N/A"),
                collaborators=trial.get("collaborators", "None"),
                funder_type=trial.get("funder_type", "N/A"),
                sex=trial.get("sex", "N/A"),
                age=trial.get("age", "N/A"),
                enrollment=trial.get("enrollment", "N/A"),
                study_type=trial.get("study_type", "N/A"),
                other_ids=trial.get("other_ids", "N/A"),
                start_date=trial.get("start_date", "N/A"),
                primary_completion_date=trial.get("primary_completion_date", "N/A"),
                completion_date=trial.get("completion_date", "N/A"),
                first_posted=trial.get("first_posted", "N/A"),
                results_first_posted=trial.get("results_first_posted", "N/A"),
                last_update_posted=trial.get("last_update_posted", "N/A"),
                study_documents=trial.get("study_documents", "None"),
                metadata=trial_metadata,
            )
        )

    return data_candidates
