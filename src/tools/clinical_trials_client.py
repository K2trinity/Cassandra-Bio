"""
ClinicalTrials.gov Client - Bio-Short-Seller Clinical Trial Failure Detector

This module provides tools to search ClinicalTrials.gov for terminated, suspended,
or withdrawn clinical trials - critical "dark data" for biomedical due diligence.

Key Function:
- search_failed_trials: Find trials with negative outcomes and extract termination reasons

Official ClinicalTrials.gov API v2 Documentation:
https://clinicaltrials.gov/data-api/api
"""

import requests
import time
from typing import List, Dict, Optional
from loguru import logger


# ========== Configuration ==========
CLINICALTRIALS_API_BASE = "https://clinicaltrials.gov/api/v2/studies"
DEFAULT_TIMEOUT = 30  # seconds
MAX_RETRIES = 3


def search_failed_trials(
    keyword: str,
    max_results: int = 20,
    include_statuses: Optional[List[str]] = None,
    retries: int = MAX_RETRIES
) -> List[Dict[str, str]]:
    """
    Search ClinicalTrials.gov for studies with negative outcomes.
    
    This function specifically targets trials that were terminated, suspended, or withdrawn,
    which often indicate safety concerns, lack of efficacy, or funding issues - all critical
    for biomedical short-selling due diligence.
    
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
        # Default to statuses indicating study problems
        include_statuses = ["TERMINATED", "SUSPENDED", "WITHDRAWN"]
    
    logger.info(f"Searching ClinicalTrials.gov: '{keyword}' (statuses: {include_statuses})")
    
    # Build query parameters
    # API documentation: https://clinicaltrials.gov/data-api/api#searchStudies
    params = {
        "query.term": keyword,
        "filter.overallStatus": ",".join(include_statuses),
        "pageSize": min(max_results, 1000),  # API limit
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
        )
    }
    
    for attempt in range(retries):
        try:
            response = requests.get(
                CLINICALTRIALS_API_BASE,
                params=params,
                timeout=DEFAULT_TIMEOUT,
                headers={"User-Agent": "Bio-Short-Seller/1.0"}
            )
            
            response.raise_for_status()
            data = response.json()
            
            # Parse results
            studies = data.get("studies", [])
            total_count = data.get("totalCount", 0)
            
            logger.success(f"Found {len(studies)} failed trials (total matches: {total_count})")
            
            parsed_trials = []
            for study in studies:
                trial_data = _parse_clinical_trial(study)
                if trial_data:
                    parsed_trials.append(trial_data)
            
            return parsed_trials
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"ClinicalTrials.gov request attempt {attempt + 1}/{retries} failed: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                logger.error(f"ClinicalTrials.gov search failed after {retries} attempts")
                raise
        except Exception as e:
            logger.error(f"Unexpected error in search_failed_trials: {e}")
            raise
    
    return []


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
        interventions_str = ", ".join(intervention_names) if intervention_names else "Not specified"

        # ── Outcome Measures ─────────────────────────────────────────────────
        primary_outcomes = outcomes_module.get("primaryOutcomes", [])
        primary_outcome_measures = (
            "; ".join(o.get("measure", "") for o in primary_outcomes if o.get("measure"))
            or "Not specified"
        )

        secondary_outcomes = outcomes_module.get("secondaryOutcomes", [])
        secondary_outcome_measures = (
            "; ".join(o.get("measure", "") for o in secondary_outcomes if o.get("measure"))
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

        # ── Dates ─────────────────────────────────────────────────────────────
        start_date = status_module.get("startDateStruct", {}).get("date", "Unknown")
        primary_completion_date = status_module.get("primaryCompletionDateStruct", {}).get("date", "Unknown")
        completion_date = status_module.get("completionDateStruct", {}).get("date", "Unknown")
        first_posted = status_module.get("studyFirstPostDateStruct", {}).get("date", "Unknown")
        results_first_posted = status_module.get("resultsFirstPostDateStruct", {}).get("date", "N/A")
        last_update_posted = status_module.get("lastUpdatePostDateStruct", {}).get("date", "Unknown")

        # ── Study Documents ────────────────────────────────────────────────────
        large_doc_module = document_section.get("largeDocumentModule", {})
        large_docs = large_doc_module.get("largeDocs", [])
        study_documents = (
            "; ".join(doc.get("label", "") for doc in large_docs if doc.get("label"))
            or "None"
        )

        return {
            # Core identification
            "nct_id": nct_id,
            "title": title,
            "official_title": official_title,
            "url": url,
            "acronym": acronym,
            "other_ids": other_ids,
            # Status
            "status": status,
            "why_stopped": why_stopped,
            # Description & results
            "brief_summary": brief_summary,
            "has_results": has_results,
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
            "phase": phase,
            "enrollment": enrollment,
            "study_type": study_type,
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
        "fields": "NCTId,HasResults,ResultsSection"
    }
    
    for attempt in range(retries):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=DEFAULT_TIMEOUT,
                headers={"User-Agent": "Bio-Short-Seller/1.0"}
            )
            
            response.raise_for_status()
            data = response.json()
            
            studies = data.get("studies", [])
            if not studies:
                logger.warning(f"No data found for {nct_id}")
                return None
            
            study = studies[0]
            has_results = study.get("hasResults", False)
            
            if not has_results:
                logger.info(f"{nct_id} has no results posted yet")
                return {
                    "nct_id": nct_id,
                    "has_results": False,
                    "results_url": f"https://clinicaltrials.gov/study/{nct_id}/results"
                }
            
            # Parse results section
            results_section = study.get("resultsSection", {})
            
            # Outcome measures
            outcome_measures_module = results_section.get("outcomeMeasuresModule", {})
            outcome_measures = outcome_measures_module.get("outcomeMeasures", [])
            
            # Adverse events
            adverse_events_module = results_section.get("adverseEventsModule", {})
            
            # Participant flow
            participant_flow_module = results_section.get("participantFlowModule", {})
            
            # Baseline characteristics
            baseline_module = results_section.get("baselineCharacteristicsModule", {})
            
            logger.success(f"Retrieved results for {nct_id}: {len(outcome_measures)} outcomes, "
                          f"AE data: {bool(adverse_events_module)}")
            
            return {
                "nct_id": nct_id,
                "has_results": True,
                "outcome_measures": outcome_measures,
                "adverse_events": adverse_events_module,
                "participant_flow": participant_flow_module,
                "baseline_characteristics": baseline_module,
                "results_url": f"https://clinicaltrials.gov/study/{nct_id}/results"
            }
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"Results fetch attempt {attempt + 1}/{retries} failed: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                logger.error(f"Failed to fetch results for {nct_id} after {retries} attempts")
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
    if not results_data or not results_data.get('has_results'):
        return []
    
    adverse_events_module = results_data.get('adverse_events', {})
    if not adverse_events_module:
        return []
    
    event_groups = adverse_events_module.get('eventGroups', [])
    serious_events = adverse_events_module.get('seriousEvents', [])
    other_events = adverse_events_module.get('otherEvents', [])
    
    formatted_events = []
    
    # Process serious events
    for event in serious_events:
        stats = event.get('stats', [])
        for stat in stats:
            formatted_events.append({
                'term': event.get('term', 'Unknown'),
                'category': 'Serious',
                'frequency': stat.get('numEvents', 0),
                'affected': stat.get('numAffected', 0),
                'at_risk': stat.get('numAtRisk', 0),
                'group_id': stat.get('groupId', 'Unknown')
            })
    
    # Process other events
    for event in other_events:
        stats = event.get('stats', [])
        for stat in stats:
            formatted_events.append({
                'term': event.get('term', 'Unknown'),
                'category': 'Other',
                'frequency': stat.get('numEvents', 0),
                'affected': stat.get('numAffected', 0),
                'at_risk': stat.get('numAtRisk', 0),
                'group_id': stat.get('groupId', 'Unknown')
            })
    
    logger.info(f"Extracted {len(formatted_events)} adverse events")
    return formatted_events


def search_trials_by_sponsor(
    sponsor_name: str,
    max_results: int = 50,
    failed_only: bool = True
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
            include_statuses=["TERMINATED", "SUSPENDED", "WITHDRAWN"]
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
            "UNKNOWN"
        ]
        return search_failed_trials(
            keyword=sponsor_name,
            max_results=max_results,
            include_statuses=all_statuses
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
        "cardiotoxicity",
        max_results=3,
        include_statuses=["TERMINATED"]
    )
    
    for trial in trials:
        print(f"\n{trial['title']}")
        print(f"  Intervention: {trial['interventions']}")
        print(f"  Reason: {trial['why_stopped']}")
        print(f"  → {trial['url']}")
    
    # Example 3: Analyze a specific company's failures
    print("\n\n=== Example 3: Company Failure Analysis ===")
    company_trials = search_trials_by_sponsor("Novartis", max_results=10, failed_only=True)
    print(f"Found {len(company_trials)} failed Novartis trials")
    
    # Count termination reasons
    reasons = {}
    for trial in company_trials:
        reason = trial['why_stopped']
        reasons[reason] = reasons.get(reason, 0) + 1
    
    print("\nTermination Reasons:")
    for reason, count in sorted(reasons.items(), key=lambda x: x[1], reverse=True):
        print(f"  {count}x: {reason}")
    
    # Example 4: 🔥 NEW - Fetch results data
    print("\n\n=== Example 4: Trial Results Data Mining ===")
    if trials:
        nct_id = trials[0]['nct_id']
        results = fetch_trial_results(nct_id)
        
        if results and results['has_results']:
            print(f"\n{nct_id} Results Summary:")
            print(f"  Outcome Measures: {len(results.get('outcome_measures', []))}")
            
            # Extract adverse events
            ae_summary = extract_adverse_events_summary(results)
            if ae_summary:
                print(f"  Adverse Events: {len(ae_summary)} events recorded")
                
                # Show serious events
                serious = [ae for ae in ae_summary if ae['category'] == 'Serious']
                if serious:
                    print(f"\n  🔥 Serious Adverse Events:")
                    for ae in serious[:5]:  # Show top 5
                        print(f"    - {ae['term']}: {ae['affected']}/{ae['at_risk']} affected")
            
            print(f"\n  Full data: {results['results_url']}")

