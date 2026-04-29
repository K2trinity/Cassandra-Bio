"""
ClinicalTrials.gov Client

This module provides tools to search ClinicalTrials.gov API v2 and parse
study-level metadata into structured dictionaries.

Key Functions:
- search_trials: General search across configurable statuses (all-status capable)
- search_failed_trials: Convenience wrapper for terminated/suspended/withdrawn trials

Official ClinicalTrials.gov API v2 Documentation:
https://clinicaltrials.gov/data-api/api
"""

import requests
import time
import uuid
import re
from typing import Any, List, Dict, Optional
from datetime import datetime
from loguru import logger

# ========== Configuration ==========
CLINICALTRIALS_API_BASE = "https://clinicaltrials.gov/api/v2/studies"
DEFAULT_TIMEOUT = 30  # seconds
MAX_RETRIES = 3


ALL_KNOWN_STATUSES = [
    "ACTIVE_NOT_RECRUITING",
    "COMPLETED",
    "ENROLLING_BY_INVITATION",
    "NOT_YET_RECRUITING",
    "RECRUITING",
    "SUSPENDED",
    "TERMINATED",
    "WITHDRAWN",
    "UNKNOWN",
]


RESULTS_ELIGIBLE_STATUSES = {
    "COMPLETED",
    "TERMINATED",
    "SUSPENDED",
    "WITHDRAWN",
}


def _to_bool(value: object) -> bool:
    """Normalize mixed bool/string flags returned by external APIs."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def is_trial_results_candidate(trial: Dict[str, str]) -> bool:
    """
    Return whether a trial should be queried for detailed results payload.

    The policy is intentionally strict to avoid noisy no-result fetches:
    - Trial must explicitly indicate has_results=true
    - If status is available, it should be a terminal/posted-results status
    """
    if not isinstance(trial, dict):
        return False

    if not _to_bool(trial.get("has_results")):
        return False

    status = str(trial.get("status") or trial.get("study_status") or "").strip().upper()
    if not status:
        return True

    return status in RESULTS_ELIGIBLE_STATUSES


def search_trials(
    keyword: str,
    max_results: int = 50,
    include_statuses: Optional[List[str]] = None,
    retries: int = MAX_RETRIES,
    raise_on_error: bool = False,
) -> List[Dict[str, str]]:
    """
    Search ClinicalTrials.gov studies with broad status coverage and pagination.

    Args:
        keyword: Search keyword (drug/target/condition/company)
        max_results: Maximum number of studies to return (bounded by API page size and pagination)
        include_statuses: Optional statuses to filter. If None, uses ALL_KNOWN_STATUSES.
        retries: Number of retries per page request

    Returns:
        List of parsed trial dictionaries in the unified format.
    """
    statuses = include_statuses or ALL_KNOWN_STATUSES
    logger.info(
        f"Searching ClinicalTrials.gov studies: '{keyword}' (statuses={statuses})"
    )

    page_size = min(max(max_results, 1), 100)
    next_page_token = None
    parsed_trials: List[Dict[str, str]] = []

    while len(parsed_trials) < max_results:
        params = {
            "query.term": keyword,
            "filter.overallStatus": ",".join(statuses),
            "pageSize": page_size,
            "format": "json",
            "fields": (
                "NCTId,BriefTitle,OfficialTitle,Acronym,OverallStatus,BriefSummary,HasResults,"
                "Condition,InterventionName,"
                "PrimaryOutcomeMeasure,SecondaryOutcomeMeasure,OtherOutcomeMeasure,"
                "Phase,EnrollmentCount,StudyType,"
                "StartDate,PrimaryCompletionDate,CompletionDate,"
                "StudyFirstPostDate,ResultsFirstPostDate,LastUpdatePostDate,"
                "LeadSponsorName,LeadSponsorClass,CollaboratorName,"
                "Sex,MinimumAge,MaximumAge,"
                "WhyStopped,SecondaryId,LargeDocLabel"
            ),
        }
        if next_page_token:
            params["pageToken"] = next_page_token

        response_data = None
        last_error: requests.exceptions.RequestException | None = None
        for attempt in range(retries):
            try:
                response = requests.get(
                    CLINICALTRIALS_API_BASE,
                    params=params,
                    timeout=DEFAULT_TIMEOUT,
                    headers={"User-Agent": "Cassandra/1.0"},
                )
                response.raise_for_status()
                response_data = response.json()
                break
            except requests.exceptions.RequestException as e:
                last_error = e
                logger.warning(
                    f"ClinicalTrials page request attempt {attempt + 1}/{retries} failed: {e}"
                )
                if attempt < retries - 1:
                    time.sleep(2**attempt)
                else:
                    logger.error("ClinicalTrials.gov page request exhausted retries")
                    if raise_on_error and last_error is not None:
                        raise last_error
                    return parsed_trials[:max_results]

        if not response_data:
            break

        studies = response_data.get("studies", [])
        if not studies:
            break

        for study in studies:
            trial_data = _parse_clinical_trial(study)
            if trial_data:
                parsed_trials.append(trial_data)
                if len(parsed_trials) >= max_results:
                    break

        next_page_token = response_data.get("nextPageToken")
        if not next_page_token:
            break

    logger.success(f"ClinicalTrials search returned {len(parsed_trials)} studies")
    return parsed_trials[:max_results]


def search_failed_trials(
    keyword: str,
    max_results: int = 20,
    include_statuses: Optional[List[str]] = None,
    retries: int = MAX_RETRIES,
) -> List[Dict[str, str]]:
    """
    Search ClinicalTrials.gov for studies with negative outcomes.

    This function specifically targets trials that were terminated, suspended, or withdrawn,
    which often indicate safety concerns, lack of efficacy, or funding issues - all critical
    for biomedical evidence analysis.

    Args:
        keyword: Search keyword (drug name, company, condition, etc.)
        max_results: Maximum number of trials to return (default: 20, API max: 1000)
        include_statuses: List of statuses to filter for. Default:
                         ['TERMINATED', 'SUSPENDED', 'WITHDRAWN']
        retries: Number of retry attempts on network failure (default: 3)

    Returns:
        List of dictionaries containing all key ClinicalTrials.gov fields:
        - nct_id: ClinicalTrials.gov identifier (e.g., "NCT01234567")
        - title: Brief study title
        - official_title: Official full study title
        - url: Link to ClinicalTrials.gov page
        - acronym: Study acronym (if any)
        - other_ids: Secondary / registry IDs
        - status: Overall study status
        - why_stopped: Reason for termination/suspension (if available)
        - brief_summary: Brief description of the study
        - has_results: Whether results are posted ("True"/"False")
        - conditions: Medical conditions being studied
        - interventions: Drugs/treatments being tested
        - primary_outcome_measures: Primary endpoint(s)
        - secondary_outcome_measures: Secondary endpoint(s)
        - other_outcome_measures: Other endpoints
        - sponsor: Lead sponsor (developer company) name
        - collaborators: Co-sponsors / collaborators
        - funder_type: Funding class (INDUSTRY / NIH / OTHER_GOV / etc.)
        - sex: Eligible sex (ALL / MALE / FEMALE)
        - age: Eligible age range
        - phase: Clinical trial phase(s)
        - enrollment: Number of participants
        - study_type: Interventional / Observational / etc.
        - start_date: Study start date
        - primary_completion_date: Primary completion date
        - completion_date: Study completion date
        - first_posted: Date first posted on ClinicalTrials.gov
        - results_first_posted: Date results first posted
        - last_update_posted: Date of last update
        - study_documents: List of study documents (protocols, ICF, etc.)

    Example:
        >>> trials = search_failed_trials("pembrolizumab", max_results=10)
        >>> for trial in trials:
        ...     if "toxicity" in trial['why_stopped'].lower():
        ...         print(f"{trial['nct_id']}: {trial['why_stopped']}")

    Raises:
        Exception: If all retry attempts fail
    """
    if include_statuses is None:
        include_statuses = ["TERMINATED", "SUSPENDED", "WITHDRAWN"]

    return search_trials(
        keyword=keyword,
        max_results=max_results,
        include_statuses=include_statuses,
        retries=retries,
    )


def _parse_clinical_trial(study: Dict) -> Optional[Dict[str, str]]:
    """
    Parse a single clinical trial record from the ClinicalTrials.gov API response.

    Extracts all key data fields including:
    - NCT Number, Study Title, Study URL, Acronym
    - Study Status, Brief Summary, Study Results
    - Conditions, Interventions
    - Primary / Secondary / Other Outcome Measures
    - Sponsor, Collaborators, Funder Type
    - Sex, Age, Phases, Enrollment, Study Type
    - Start Date, Primary Completion Date, Completion Date
    - First Posted, Results First Posted, Last Update Posted
    - Study Documents, Other IDs

    Args:
        study: Study record from the API JSON response

    Returns:
        Dictionary with full trial metadata or None if parsing fails
    """
    try:
        protocol_section = study.get("protocolSection", {})
        identification_module = protocol_section.get("identificationModule", {})
        status_module = protocol_section.get("statusModule", {})
        conditions_module = protocol_section.get("conditionsModule", {})
        interventions_module = protocol_section.get("armsInterventionsModule", {})
        design_module = protocol_section.get("designModule", {})
        sponsor_module = protocol_section.get("sponsorCollaboratorsModule", {})
        description_module = protocol_section.get("descriptionModule", {})
        outcomes_module = protocol_section.get("outcomesModule", {})
        eligibility_module = protocol_section.get("eligibilityModule", {})
        document_section = study.get("documentSection", {})

        # ── Identification ──────────────────────────────────────────────────
        nct_id = identification_module.get("nctId", "Unknown")
        title = identification_module.get("briefTitle", "No title available")
        official_title = identification_module.get("officialTitle", title)
        acronym = identification_module.get("acronym", "N/A")

        # Other IDs (secondary / registry IDs)
        secondary_ids_raw = identification_module.get("secondaryIdInfos", [])
        other_ids = (
            ", ".join(s.get("id", "") for s in secondary_ids_raw if s.get("id"))
            or "N/A"
        )

        # Study URL
        url = f"https://clinicaltrials.gov/study/{nct_id}"

        # ── Status & Description ─────────────────────────────────────────────
        status = status_module.get("overallStatus", "Unknown")
        why_stopped = status_module.get("whyStopped", "Reason not provided")
        brief_summary = description_module.get("briefSummary", "Not available")
        has_results = str(study.get("hasResults", False))

        # ── Conditions ───────────────────────────────────────────────────────
        conditions = conditions_module.get("conditions", [])
        conditions_str = ", ".join(conditions) if conditions else "Not specified"

        # ── Interventions ────────────────────────────────────────────────────
        interventions = interventions_module.get("interventions", [])
        intervention_names = [i.get("name", "Unknown") for i in interventions]
        interventions_str = (
            ", ".join(intervention_names) if intervention_names else "Not specified"
        )

        # ── Outcome Measures ─────────────────────────────────────────────────
        primary_outcomes = outcomes_module.get("primaryOutcomes", [])
        primary_outcome_measures = (
            "; ".join(
                o.get("measure", "") for o in primary_outcomes if o.get("measure")
            )
            or "Not specified"
        )

        secondary_outcomes = outcomes_module.get("secondaryOutcomes", [])
        secondary_outcome_measures = (
            "; ".join(
                o.get("measure", "") for o in secondary_outcomes if o.get("measure")
            )
            or "Not specified"
        )

        other_outcomes = outcomes_module.get("otherOutcomes", [])
        other_outcome_measures = (
            "; ".join(o.get("measure", "") for o in other_outcomes if o.get("measure"))
            or "Not specified"
        )

        # ── Sponsor & Collaborators ──────────────────────────────────────────
        lead_sponsor = sponsor_module.get("leadSponsor", {})
        sponsor = lead_sponsor.get("name", "Unknown sponsor")
        funder_type = lead_sponsor.get("class", "N/A")  # e.g. INDUSTRY / NIH / OTHER

        collaborators = sponsor_module.get("collaborators", [])
        collaborators_str = (
            ", ".join(c.get("name", "") for c in collaborators if c.get("name"))
            or "None"
        )

        # ── Eligibility ───────────────────────────────────────────────────────
        sex = eligibility_module.get("sex", "All")
        min_age = eligibility_module.get("minimumAge", "N/A")
        max_age = eligibility_module.get("maximumAge", "N/A")
        age = (
            f"{min_age} to {max_age}"
            if (min_age != "N/A" or max_age != "N/A")
            else "Not specified"
        )

        # ── Design ────────────────────────────────────────────────────────────
        phases = design_module.get("phases", [])
        phase = ", ".join(phases) if phases else "Not specified"

        enrollment_info = design_module.get("enrollmentInfo", {})
        enrollment = str(enrollment_info.get("count", "Unknown"))

        study_type = design_module.get("studyType", "Not specified")

        design_info = (
            design_module.get("designInfo", {})
            if isinstance(design_module.get("designInfo", {}), dict)
            else {}
        )
        allocation = design_info.get("allocation") or design_module.get("allocation")
        intervention_model = (
            design_info.get("interventionModelDescription")
            or design_module.get("interventionModelDescription")
            or design_info.get("interventionModel")
            or design_module.get("interventionModel")
        )
        primary_purpose = design_info.get("primaryPurpose") or design_module.get(
            "primaryPurpose"
        )
        observational_model = design_info.get(
            "observationalModel"
        ) or design_module.get("observationalModel")
        time_perspective = design_info.get("timePerspective") or design_module.get(
            "timePerspective"
        )

        study_design_parts = [
            (
                f"Study Type: {study_type}"
                if study_type and study_type != "Not specified"
                else None
            ),
            f"Allocation: {allocation}" if allocation else None,
            f"Intervention Model: {intervention_model}" if intervention_model else None,
            f"Primary Purpose: {primary_purpose}" if primary_purpose else None,
            (
                f"Observational Model: {observational_model}"
                if observational_model
                else None
            ),
            f"Time Perspective: {time_perspective}" if time_perspective else None,
        ]
        study_design = "; ".join([x for x in study_design_parts if x]) or study_type

        # ── Dates ─────────────────────────────────────────────────────────────
        start_date = status_module.get("startDateStruct", {}).get("date", "Unknown")
        primary_completion_date = status_module.get(
            "primaryCompletionDateStruct", {}
        ).get("date", "Unknown")
        completion_date = status_module.get("completionDateStruct", {}).get(
            "date", "Unknown"
        )
        first_posted = status_module.get("studyFirstPostDateStruct", {}).get(
            "date", "Unknown"
        )
        results_first_posted = status_module.get("resultsFirstPostDateStruct", {}).get(
            "date", "N/A"
        )
        last_update_posted = status_module.get("lastUpdatePostDateStruct", {}).get(
            "date", "Unknown"
        )
        results_url = f"https://clinicaltrials.gov/study/{nct_id}/results"
        study_results = (
            "Results available"
            if has_results.lower() == "true"
            else "No posted results"
        )

        # ── Study Documents ────────────────────────────────────────────────────
        large_doc_module = document_section.get("largeDocumentModule", {})
        large_docs = large_doc_module.get("largeDocs", [])
        study_documents = (
            "; ".join(doc.get("label", "") for doc in large_docs if doc.get("label"))
            or "None"
        )

        return {
            # Core identification
            "nct_number": nct_id,
            "nct_id": nct_id,
            "title": title,
            "official_title": official_title,
            "study_url": url,
            "url": url,
            "acronym": acronym,
            "other_ids": other_ids,
            # Status
            "study_status": status,
            "status": status,
            "why_stopped": why_stopped,
            # Description & results
            "brief_summary": brief_summary,
            "has_results": has_results,
            "study_results": study_results,
            "results_url": results_url,
            # Conditions & interventions
            "conditions": conditions_str,
            "interventions": interventions_str,
            # Outcome measures
            "primary_outcome_measures": primary_outcome_measures,
            "secondary_outcome_measures": secondary_outcome_measures,
            "other_outcome_measures": other_outcome_measures,
            # Sponsor & funding
            "sponsor": sponsor,
            "collaborators": collaborators_str,
            "funder_type": funder_type,
            # Eligibility
            "sex": sex,
            "age": age,
            # Design
            "phases": phase,
            "phase": phase,
            "enrollment": enrollment,
            "study_type": study_type,
            "study_design": study_design,
            # Dates
            "start_date": start_date,
            "primary_completion_date": primary_completion_date,
            "completion_date": completion_date,
            "first_posted": first_posted,
            "results_first_posted": results_first_posted,
            "last_update_posted": last_update_posted,
            # Documents
            "study_documents": study_documents,
        }

    except Exception as e:
        logger.error(f"Failed to parse clinical trial record: {e}")
        return None


def fetch_trial_results(nct_id: str, retries: int = MAX_RETRIES) -> Optional[Dict]:
    """
    🔥 NEW: Fetch clinical trial results data (Primary Endpoints, Adverse Events).

    This function retrieves the Results Section from ClinicalTrials.gov, which contains:
    - Outcome measures (Primary/Secondary endpoints)
    - Participant flow data
    - Baseline characteristics
    - Adverse events (crucial for safety analysis)

    These data are often more "truthful" than published papers as they are legally required
    and less subject to publication bias or statistical manipulation.

    Args:
        nct_id: ClinicalTrials.gov identifier (e.g., "NCT01234567")
        retries: Number of retry attempts on network failure

    Returns:
        Dictionary containing:
        - nct_id: Trial identifier
        - has_results: Boolean indicating if results are available
        - outcome_measures: List of primary and secondary outcomes with data
        - adverse_events: Detailed adverse event data by group
        - participant_flow: Enrollment and dropout data
        - baseline_characteristics: Demographics and baseline measures
        - results_url: Direct link to results section

    Example:
        >>> results = fetch_trial_results("NCT02576639")
        >>> if results and results['adverse_events']:
        ...     print(f"Found {len(results['adverse_events'])} adverse events")
    """
    logger.info(f"Fetching results data for {nct_id}")

    url = f"{CLINICALTRIALS_API_BASE}/{nct_id}"
    params = {
        "format": "json",
    }

    for attempt in range(retries):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=DEFAULT_TIMEOUT,
                headers={"User-Agent": "Cassandra/1.0"},
            )

            response.raise_for_status()
            data = response.json()

            # ClinicalTrials v2 details endpoint commonly returns a single study object.
            # Keep backward-compat parsing for list-wrapped payloads as well.
            study = data
            if isinstance(data, dict) and isinstance(data.get("studies"), list):
                studies = data.get("studies", [])
                if not studies:
                    logger.info(f"No study payload found for {nct_id}")
                    return None
                study = studies[0]

            if not isinstance(study, dict):
                logger.warning(f"Unexpected study payload shape for {nct_id}")
                return None

            has_results = _to_bool(study.get("hasResults", False))

            if not has_results:
                logger.info(f"{nct_id} has no results posted yet")
                return {
                    "nct_id": nct_id,
                    "has_results": False,
                    "results_url": f"https://clinicaltrials.gov/study/{nct_id}/results",
                }

            # Parse results section
            results_section = study.get("resultsSection", {}) or {}
            if not results_section:
                logger.warning(
                    f"{nct_id} marked hasResults=true but resultsSection is empty"
                )
                return {
                    "nct_id": nct_id,
                    "has_results": False,
                    "results_url": f"https://clinicaltrials.gov/study/{nct_id}/results",
                }

            # Outcome measures
            outcome_measures_module = results_section.get("outcomeMeasuresModule", {})
            outcome_measures = outcome_measures_module.get("outcomeMeasures", [])

            # Adverse events
            adverse_events_module = results_section.get("adverseEventsModule", {})

            # Participant flow
            participant_flow_module = results_section.get("participantFlowModule", {})

            # Baseline characteristics
            baseline_module = results_section.get("baselineCharacteristicsModule", {})

            logger.success(
                f"Retrieved results for {nct_id}: {len(outcome_measures)} outcomes, "
                f"AE data: {bool(adverse_events_module)}"
            )

            return {
                "nct_id": nct_id,
                "has_results": True,
                "outcome_measures": outcome_measures,
                "adverse_events": adverse_events_module,
                "participant_flow": participant_flow_module,
                "baseline_characteristics": baseline_module,
                "results_url": f"https://clinicaltrials.gov/study/{nct_id}/results",
            }

        except requests.exceptions.RequestException as e:
            logger.warning(f"Results fetch attempt {attempt + 1}/{retries} failed: {e}")
            if attempt < retries - 1:
                time.sleep(2**attempt)
            else:
                logger.error(
                    f"Failed to fetch results for {nct_id} after {retries} attempts"
                )
                return None
        except Exception as e:
            logger.error(f"Unexpected error fetching results for {nct_id}: {e}")
            return None

    return None


def extract_adverse_events_summary(results_data: Dict) -> List[Dict[str, str]]:
    """
    Extract and format adverse events from trial results data.

    Args:
        results_data: Dictionary returned by fetch_trial_results()

    Returns:
        List of adverse event dictionaries with:
        - term: Adverse event term
        - category: Event category (e.g., "Serious", "Other")
        - frequency: Number of occurrences
        - percentage: Percentage of participants affected
        - group: Treatment group
    """
    if not results_data or not results_data.get("has_results"):
        return []

    adverse_events_module = results_data.get("adverse_events", {})
    if not adverse_events_module:
        return []

    event_groups = adverse_events_module.get("eventGroups", [])
    serious_events = adverse_events_module.get("seriousEvents", [])
    other_events = adverse_events_module.get("otherEvents", [])

    formatted_events = []

    # Process serious events
    for event in serious_events:
        stats = event.get("stats", [])
        for stat in stats:
            formatted_events.append(
                {
                    "term": event.get("term", "Unknown"),
                    "category": "Serious",
                    "frequency": stat.get("numEvents", 0),
                    "affected": stat.get("numAffected", 0),
                    "at_risk": stat.get("numAtRisk", 0),
                    "group_id": stat.get("groupId", "Unknown"),
                }
            )

    # Process other events
    for event in other_events:
        stats = event.get("stats", [])
        for stat in stats:
            formatted_events.append(
                {
                    "term": event.get("term", "Unknown"),
                    "category": "Other",
                    "frequency": stat.get("numEvents", 0),
                    "affected": stat.get("numAffected", 0),
                    "at_risk": stat.get("numAtRisk", 0),
                    "group_id": stat.get("groupId", "Unknown"),
                }
            )

    logger.info(f"Extracted {len(formatted_events)} adverse events")
    return formatted_events


def search_trials_by_sponsor(
    sponsor_name: str, max_results: int = 50, failed_only: bool = True
) -> List[Dict[str, str]]:
    """
    Search for all trials by a specific sponsor/company.

    Useful for analyzing a company's clinical trial track record.

    Args:
        sponsor_name: Company or institution name (e.g., "Pfizer", "AstraZeneca")
        max_results: Maximum number of trials to return
        failed_only: If True, only return TERMINATED/SUSPENDED/WITHDRAWN trials

    Returns:
        List of trial dictionaries (same format as search_failed_trials)

    Example:
        >>> trials = search_trials_by_sponsor("Theranos", failed_only=True)
        >>> print(f"Found {len(trials)} failed trials")
    """
    if failed_only:
        return search_failed_trials(
            keyword=sponsor_name,
            max_results=max_results,
            include_statuses=["TERMINATED", "SUSPENDED", "WITHDRAWN"],
        )
    else:
        # Search all statuses
        all_statuses = [
            "ACTIVE_NOT_RECRUITING",
            "COMPLETED",
            "ENROLLING_BY_INVITATION",
            "NOT_YET_RECRUITING",
            "RECRUITING",
            "SUSPENDED",
            "TERMINATED",
            "WITHDRAWN",
            "UNKNOWN",
        ]
        return search_failed_trials(
            keyword=sponsor_name, max_results=max_results, include_statuses=all_statuses
        )


# ========== Example Usage ==========
if __name__ == "__main__":
    # Example 1: Search for failed pembrolizumab trials
    print("\n=== Example 1: Failed Pembrolizumab Trials ===")
    trials = search_failed_trials("pembrolizumab", max_results=5)

    for trial in trials:
        print(f"\n{trial['nct_id']}: {trial['title']}")
        print(f"  Status: {trial['status']}")
        print(f"  Phase: {trial['phase']}")
        print(f"  🔥 Why Stopped: {trial['why_stopped']}")
        print(f"  Sponsor: {trial['sponsor']}")
        print(f"  Link: {trial['url']}")

    # Example 2: Search for all terminated cardiotoxicity trials
    print("\n\n=== Example 2: Cardiotoxicity Terminations ===")
    trials = search_failed_trials(
        "cardiotoxicity", max_results=3, include_statuses=["TERMINATED"]
    )

    for trial in trials:
        print(f"\n{trial['title']}")
        print(f"  Intervention: {trial['interventions']}")
        print(f"  Reason: {trial['why_stopped']}")
        print(f"  → {trial['url']}")

    # Example 3: Analyze a specific company's failures
    print("\n\n=== Example 3: Company Failure Analysis ===")
    company_trials = search_trials_by_sponsor(
        "Novartis", max_results=10, failed_only=True
    )
    print(f"Found {len(company_trials)} failed Novartis trials")

    # Count termination reasons
    reasons = {}
    for trial in company_trials:
        reason = trial["why_stopped"]
        reasons[reason] = reasons.get(reason, 0) + 1

    print("\nTermination Reasons:")
    for reason, count in sorted(reasons.items(), key=lambda x: x[1], reverse=True):
        print(f"  {count}x: {reason}")

    # Example 4: 🔥 NEW - Fetch results data
    print("\n\n=== Example 4: Trial Results Data Mining ===")
    if trials:
        nct_id = trials[0]["nct_id"]
        results = fetch_trial_results(nct_id)

        if results and results["has_results"]:
            print(f"\n{nct_id} Results Summary:")
            print(f"  Outcome Measures: {len(results.get('outcome_measures', []))}")

            # Extract adverse events
            ae_summary = extract_adverse_events_summary(results)
            if ae_summary:
                print(f"  Adverse Events: {len(ae_summary)} events recorded")

                # Show serious events
                serious = [ae for ae in ae_summary if ae["category"] == "Serious"]
                if serious:
                    print(f"\n  🔥 Serious Adverse Events:")
                    for ae in serious[:5]:  # Show top 5
                        print(
                            f"    - {ae['term']}: {ae['affected']}/{ae['at_risk']} affected"
                        )

            print(f"\n  Full data: {results['results_url']}")


def _coerce_text(value: object, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value if item is not None) or default
    return str(value)


_LEGAL_ENTITY_SUFFIXES = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "company",
    "co",
    "ltd",
    "limited",
    "plc",
    "ag",
    "sa",
    "nv",
    "llc",
}


def _clinical_ownership_match(
    trial: Dict[str, Any],
    requested_ticker: str | None,
    sponsor: str,
) -> str | None:
    """Return sponsor/collaborator ownership match for requested ticker."""
    if requested_ticker is None:
        return "sponsor"

    terms = _ownership_terms_for_ticker(requested_ticker)
    if not terms:
        return None

    if _text_matches_company(sponsor, terms):
        return "sponsor"

    collaborators = _coerce_text(trial.get("collaborators"), "")
    if _text_matches_company(collaborators, terms):
        return "collaborator"

    return None


def _ownership_terms_for_ticker(ticker: str) -> list[str]:
    try:
        from src.kline.ticker_resolver import TickerResolver

        company = TickerResolver().resolve(ticker)
    except ValueError:
        return []

    raw_terms = [company.name, *company.aliases]
    terms: list[str] = []
    for raw_term in raw_terms:
        normalized = _normalize_company_term(raw_term)
        if normalized and normalized not in terms:
            terms.append(normalized)
        compact = normalized.replace(" ", "")
        if " " in normalized and compact and compact not in terms:
            terms.append(compact)
    return terms


def _text_matches_company(text: str, terms: list[str]) -> bool:
    normalized_text = _normalize_company_term(text)
    text_words = set(normalized_text.split())
    for term in terms:
        if " " in term:
            if term in normalized_text:
                return True
        elif term in text_words:
            return True
    return False


def _normalize_company_term(value: object) -> str:
    text = str(value or "").lower()
    words = re.findall(r"[a-z0-9]+", text)
    filtered = [word for word in words if word not in _LEGAL_ENTITY_SUFFIXES]
    return " ".join(filtered)


def normalize_biotech_events(
    trials: List[Dict[str, Any]],
    source: str = "clinicaltrials",
    requested_ticker: str | None = None,
) -> List[Dict[str, Any]]:
    """
    Normalize ClinicalTrials.gov payloads into consistent biotech_events schema.

    Args:
        trials: List of trial dictionaries from search_trials() or similar
        source: Data source identifier (default: "clinicaltrials")
        requested_ticker: Chart ticker requested by the user; source sponsor remains metadata.

    Returns:
        List of normalized event dictionaries with schema:
        {
            "id": "...",
            "date": "YYYY-MM-DD",
            "type": "clinical_readout",
            "priority": 1-5,
            "ticker": "COMPANY",
            "disease_area": "...",
            "catalyst": "...",
            "sentiment": "positive" | "negative" | "neutral",
            "price_impact": None,
            "source": "clinicaltrials",
        }
    """
    events = []

    for trial in trials:
        try:
            # Extract usable date (prefer results_first_posted, fallback to completion_date)
            event_date = trial.get("results_first_posted") or trial.get(
                "completion_date"
            )

            if not event_date or event_date == "Unknown" or event_date == "N/A":
                logger.debug(
                    f"Skipping trial {trial.get('nct_id')} with no usable date"
                )
                continue

            # Parse date to YYYY-MM-DD format
            try:
                if isinstance(event_date, str) and len(event_date) == 10:
                    # Already in YYYY-MM-DD format
                    date_str = event_date
                else:
                    # Try parsing various formats
                    date_obj = datetime.strptime(str(event_date), "%Y-%m-%d")
                    date_str = date_obj.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                logger.warning(
                    f"Invalid date format for {trial.get('nct_id')}: {event_date}"
                )
                continue

            # Determine sentiment based on status
            status = str(trial.get("status", "")).upper()
            if status in {"COMPLETED", "ACTIVE_NOT_RECRUITING"}:
                sentiment = "positive"
                priority = 4
            elif status in {"TERMINATED", "SUSPENDED", "WITHDRAWN"}:
                sentiment = "negative"
                priority = 5
            else:
                sentiment = "neutral"
                priority = 2

            # Requested ticker owns the chart event; sponsor remains source attribution.
            sponsor = _coerce_text(trial.get("sponsor"), "UNKNOWN")
            raw_ticker = sponsor.split()[0] if sponsor else None
            if requested_ticker is not None:
                ticker = requested_ticker.strip().upper()
            else:
                ticker = sponsor.split()[0] if sponsor else "UNKNOWN"

            # Extract disease area from conditions
            conditions = _coerce_text(trial.get("conditions"), "")
            disease_area = conditions.split(",")[0] if conditions else ""

            # Build catalyst description
            trial_title = trial.get("title", "Clinical Trial")
            phase = trial.get("phase", "")
            phase_str = f" ({phase})" if phase and phase != "Not specified" else ""
            catalyst = f"Clinical Trial: {trial_title}{phase_str}"
            nct_id = trial.get("nct_id") or trial.get("nct_number")
            valid_nct_id = (
                nct_id if nct_id and nct_id not in {"Unknown", "N/A"} else None
            )
            source_url = trial.get("url") or trial.get("study_url")
            if not source_url and valid_nct_id:
                source_url = f"https://clinicaltrials.gov/study/{valid_nct_id}"
            metadata = {
                "phase": phase,
                "status": trial.get("status"),
                "raw_ticker": raw_ticker,
                "has_results": _to_bool(trial.get("has_results")),
            }
            why_stopped = trial.get("why_stopped")
            if why_stopped and why_stopped not in {"Reason not provided", "N/A"}:
                metadata["why_stopped"] = why_stopped

            event = {
                "id": str(uuid.uuid4()),
                "date": date_str,
                "type": "clinical_readout",
                "priority": priority,
                "ticker": ticker,
                "disease_area": disease_area,
                "catalyst": catalyst,
                "sentiment": sentiment,
                "price_impact": None,
                "source": source,
                "source_entity": sponsor,
                "source_url": source_url,
                "source_ids": [valid_nct_id] if valid_nct_id else [],
                "confidence": "high" if valid_nct_id else "medium",
                "metadata": metadata,
            }

            events.append(event)

        except Exception as e:
            logger.error(f"Error normalizing clinical trial {trial.get('nct_id')}: {e}")
            continue

    return events


def normalize_clinical_trial_milestone_events(
    trials: List[Dict[str, Any]],
    source: str = "clinicaltrials",
    requested_ticker: str | None = None,
) -> List[Dict[str, Any]]:
    """Expand ClinicalTrials records into phase2 milestone events."""
    from src.kline.event_filter import enrich_event_metadata

    events: List[Dict[str, Any]] = []
    for trial in trials:
        try:
            sponsor = _coerce_text(trial.get("sponsor"), "UNKNOWN")
            entity_match = _clinical_ownership_match(trial, requested_ticker, sponsor)
            if requested_ticker is not None and entity_match is None:
                logger.debug(
                    "Skipping ClinicalTrials milestone event without ticker ownership: "
                    f"{requested_ticker}/{trial.get('nct_id')}"
                )
                continue
            if requested_ticker is not None:
                ticker = requested_ticker.strip().upper()
            else:
                ticker = sponsor.split()[0] if sponsor else "UNKNOWN"
            nct_id = trial.get("nct_id") or trial.get("nct_number")
            valid_nct_id = (
                nct_id if nct_id and nct_id not in {"Unknown", "N/A"} else None
            )
            title = _coerce_text(trial.get("title"), "Clinical Trial")
            phase = _coerce_text(trial.get("phase") or trial.get("phases"), "")
            status = _coerce_text(trial.get("status") or trial.get("study_status"), "")
            conditions = _coerce_text(trial.get("conditions"), "")
            interventions = _coerce_text(trial.get("interventions"), "")
            disease_area = conditions.split(",")[0] if conditions else ""
            source_url = trial.get("url") or trial.get("study_url")
            if not source_url and valid_nct_id:
                source_url = f"https://clinicaltrials.gov/study/{valid_nct_id}"

            milestone_specs = [
                (
                    "trial_results_posted",
                    trial.get("results_first_posted"),
                    "Results posted",
                ),
                (
                    "trial_primary_completion",
                    trial.get("primary_completion_date"),
                    "Primary completion",
                ),
                ("trial_completion", trial.get("completion_date"), "Study completion"),
                (
                    "trial_status_change",
                    trial.get("last_update_posted"),
                    f"Status update: {status or 'Unknown'}",
                ),
            ]
            if status.upper() in {"TERMINATED", "SUSPENDED", "WITHDRAWN"}:
                milestone_specs = [
                    (
                        "trial_termination",
                        trial.get("completion_date") or trial.get("last_update_posted"),
                        f"Trial {status.lower()}",
                    ),
                    (
                        "trial_status_change",
                        trial.get("last_update_posted"),
                        f"Status update: {status}",
                    ),
                ]

            seen: set[tuple[str, str]] = set()
            for event_type, raw_date, label in milestone_specs:
                date_str = _clinical_event_date(raw_date)
                if not date_str:
                    continue
                key = (event_type, date_str)
                if key in seen:
                    continue
                seen.add(key)

                sentiment = (
                    "negative"
                    if event_type == "trial_termination"
                    else (
                        "positive"
                        if event_type == "trial_results_posted"
                        else "neutral"
                    )
                )
                priority = (
                    1
                    if event_type in {"trial_results_posted", "trial_termination"}
                    else 2
                )
                metadata = {
                    "phase": phase,
                    "status": status,
                    "has_results": _to_bool(trial.get("has_results")),
                    "interventions": interventions,
                    "entity_match": entity_match or "sponsor",
                    "raw_type": event_type,
                }
                why_stopped = trial.get("why_stopped")
                if why_stopped and why_stopped not in {"Reason not provided", "N/A"}:
                    metadata["why_stopped"] = why_stopped
                event = {
                    "id": str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"{ticker}|{valid_nct_id}|{event_type}|{date_str}",
                        )
                    ),
                    "date": date_str,
                    "type": event_type,
                    "category": "clinical",
                    "priority": priority,
                    "ticker": ticker,
                    "disease_area": disease_area,
                    "catalyst": f"{label}: {title}",
                    "title": f"{label}: {title}",
                    "summary": f"{label} for {title}",
                    "sentiment": sentiment,
                    "price_impact": None,
                    "source": source,
                    "source_entity": sponsor,
                    "source_url": source_url,
                    "source_ids": [valid_nct_id] if valid_nct_id else [],
                    "confidence": "high" if valid_nct_id else "medium",
                    "metadata": metadata,
                }
                events.append(enrich_event_metadata(event))
        except Exception as e:
            logger.error(
                f"Error normalizing clinical trial milestones {trial.get('nct_id')}: {e}"
            )
            continue
    return events


def _clinical_event_date(value: object) -> str | None:
    if not value or value in {"Unknown", "N/A"}:
        return None
    try:
        if isinstance(value, str) and len(value) == 10:
            datetime.strptime(value, "%Y-%m-%d")
            return value
        return datetime.strptime(str(value), "%Y-%m-%d").strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None
