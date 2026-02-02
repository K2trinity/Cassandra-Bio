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
        List of dictionaries containing:
        - nct_id: ClinicalTrials.gov identifier (e.g., "NCT01234567")
        - title: Official study title
        - status: Overall study status
        - why_stopped: Reason for termination/suspension (if available)
        - conditions: Medical conditions being studied
        - interventions: Drugs/treatments being tested
        - phase: Clinical trial phase (e.g., "Phase 2", "Phase 3")
        - enrollment: Number of participants
        - start_date: Study start date
        - completion_date: Study completion/termination date
        - sponsor: Primary study sponsor
        - url: Link to ClinicalTrials.gov page
    
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
        "fields": "NCTId,BriefTitle,OverallStatus,WhyStopped,Condition,InterventionName,"
                  "Phase,EnrollmentCount,StartDate,CompletionDate,LeadSponsorName"
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
    
    Args:
        study: Study record from the API JSON response
    
    Returns:
        Dictionary with trial metadata or None if parsing fails
    """
    try:
        protocol_section = study.get("protocolSection", {})
        identification_module = protocol_section.get("identificationModule", {})
        status_module = protocol_section.get("statusModule", {})
        conditions_module = protocol_section.get("conditionsModule", {})
        interventions_module = protocol_section.get("armsInterventionsModule", {})
        design_module = protocol_section.get("designModule", {})
        sponsor_module = protocol_section.get("sponsorCollaboratorsModule", {})
        
        # NCT ID
        nct_id = identification_module.get("nctId", "Unknown")
        
        # Title
        title = identification_module.get("briefTitle", "No title available")
        
        # Status
        status = status_module.get("overallStatus", "Unknown")
        
        # 🔥 Critical: Why was the study stopped?
        why_stopped = status_module.get("whyStopped", "Reason not provided")
        
        # Conditions being studied
        conditions = conditions_module.get("conditions", [])
        conditions_str = ", ".join(conditions) if conditions else "Not specified"
        
        # Interventions (drugs/treatments)
        interventions = interventions_module.get("interventions", [])
        intervention_names = [
            interv.get("name", "Unknown") 
            for interv in interventions
        ]
        interventions_str = ", ".join(intervention_names) if intervention_names else "Not specified"
        
        # Phase
        phases = design_module.get("phases", [])
        phase = phases[0] if phases else "Not specified"
        
        # Enrollment
        enrollment_info = design_module.get("enrollmentInfo", {})
        enrollment = enrollment_info.get("count", "Unknown")
        
        # Dates
        start_date_struct = status_module.get("startDateStruct", {})
        start_date = start_date_struct.get("date", "Unknown")
        
        completion_date_struct = status_module.get("completionDateStruct", {}) or \
                                 status_module.get("primaryCompletionDateStruct", {})
        completion_date = completion_date_struct.get("date", "Unknown")
        
        # Sponsor
        lead_sponsor = sponsor_module.get("leadSponsor", {})
        sponsor = lead_sponsor.get("name", "Unknown sponsor")
        
        # URL
        url = f"https://clinicaltrials.gov/study/{nct_id}"
        
        return {
            "nct_id": nct_id,
            "title": title,
            "status": status,
            "why_stopped": why_stopped,
            "conditions": conditions_str,
            "interventions": interventions_str,
            "phase": phase,
            "enrollment": str(enrollment),
            "start_date": start_date,
            "completion_date": completion_date,
            "sponsor": sponsor,
            "url": url,
        }
        
    except Exception as e:
        logger.error(f"Failed to parse clinical trial record: {e}")
        return None


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
