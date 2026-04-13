"""
ClinicalTrials.gov Results Data Client

🚨 P1 修正：PDF失败后的"第二铲子"
当PDF下载失败时，自动从ClinicalTrials.gov抓取结构化结果数据。

功能：
- 获取试验结果数据（Outcome Measures）
- 提取不良事件表格（Adverse Events）
- 解析特定系统器官分类（SOC）的事件率
- 返回结构化数据而非估计值

API文档：https://clinicaltrials.gov/api/v2/studies
"""

import requests
from typing import Optional, Dict, List, Any
from loguru import logger
import time


class ClinicalTrialsResultsClient:
    """ClinicalTrials.gov结果数据抓取客户端"""
    
    BASE_URL = "https://clinicaltrials.gov/api/v2/studies"
    DEFAULT_TIMEOUT = 30
    
    def __init__(self):
        """初始化客户端"""
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'BioHarvester/1.0 (Research Tool)'
        })
    
    def get_results(self, nct_id: str, retries: int = 3) -> Optional[Dict[str, Any]]:
        """
        获取试验的完整结果数据
        
        Args:
            nct_id: NCT ID (e.g., 'NCT03574597')
            retries: 重试次数
        
        Returns:
            结构化结果数据，包括:
            {
                'has_results': bool,
                'outcome_measures': List[Dict],
                'adverse_events': Dict,
                'participant_flow': Dict
            }
        """
        logger.info(f"🔍 Fetching results for {nct_id} from ClinicalTrials.gov")
        
        url = f"{self.BASE_URL}/{nct_id}"
        
        for attempt in range(retries):
            try:
                response = self.session.get(url, timeout=self.DEFAULT_TIMEOUT)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # 检查是否有结果数据
                    results_section = data.get('resultsSection')
                    
                    if not results_section:
                        logger.warning(f"⚠️ {nct_id} has no results data on ClinicalTrials.gov")
                        return {'has_results': False}
                    
                    logger.success(f"✅ Found results data for {nct_id}")
                    
                    return {
                        'has_results': True,
                        'outcome_measures': results_section.get('outcomeMeasuresModule', {}),
                        'adverse_events': results_section.get('adverseEventsModule', {}),
                        'participant_flow': results_section.get('participantFlowModule', {}),
                        'baseline_characteristics': results_section.get('baselineCharacteristicsModule', {})
                    }
                
                elif response.status_code == 404:
                    logger.error(f"❌ {nct_id} not found on ClinicalTrials.gov")
                    return None
                
                else:
                    logger.warning(f"⚠️ HTTP {response.status_code} (attempt {attempt+1}/{retries})")
            
            except Exception as e:
                logger.warning(f"⚠️ Request failed (attempt {attempt+1}/{retries}): {e}")
            
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
        
        logger.error(f"❌ Failed to fetch results for {nct_id} after {retries} attempts")
        return None
    
    def extract_adverse_event_rate(
        self, 
        results_data: Dict[str, Any], 
        soc_term: str = "Gastrointestinal disorders",
        specific_term: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        从结果数据中提取特定不良事件的发生率
        
        Args:
            results_data: get_results()返回的数据
            soc_term: 系统器官分类（System Organ Class）
            specific_term: 具体不良事件名称（可选）
        
        Returns:
            {
                'soc_term': str,
                'treatment_group': {
                    'affected': int,
                    'at_risk': int,
                    'percentage': float
                },
                'control_group': {
                    'affected': int,
                    'at_risk': int,
                    'percentage': float
                }
            }
        """
        if not results_data or not results_data.get('has_results'):
            logger.warning("⚠️ No results data available")
            return None
        
        ae_module = results_data.get('adverse_events', {})
        
        if not ae_module:
            logger.warning("⚠️ No adverse events module in results")
            return None
        
        logger.info(f"🔍 Searching for '{soc_term}' adverse events...")
        
        # 查找事件组分类
        event_groups = ae_module.get('eventGroups', [])
        
        if not event_groups:
            logger.warning("⚠️ No event groups found")
            return None
        
        # 这里需要根据实际API结构解析
        # ClinicalTrials.gov的结果数据结构较复杂，需要实际测试
        logger.info(f"📊 Found {len(event_groups)} event groups")
        
        # TODO: 实现具体的解析逻辑
        # 当前返回原始数据供调试
        return {
            'raw_data': ae_module,
            'note': 'Parsing logic needs to be implemented based on actual API structure'
        }
    
    def extract_discontinuation_rate(
        self,
        results_data: Dict[str, Any],
        reason: str = "Adverse Event"
    ) -> Optional[Dict[str, Any]]:
        """
        提取因特定原因停药的比例
        
        Args:
            results_data: get_results()返回的数据
            reason: 停药原因
        
        Returns:
            停药率数据
        """
        if not results_data or not results_data.get('has_results'):
            return None
        
        flow_module = results_data.get('participant_flow', {})
        
        if not flow_module:
            logger.warning("⚠️ No participant flow data available")
            return None
        
        logger.info(f"🔍 Searching for discontinuation due to '{reason}'...")
        
        # 解析participant flow数据
        # TODO: 实现具体解析逻辑
        
        return {
            'raw_data': flow_module,
            'note': 'Parsing logic needs to be implemented'
        }


# 🚨 P1 修正：在PDF下载失败时自动调用此客户端
def get_trial_results_as_fallback(nct_id: str) -> Optional[Dict[str, Any]]:
    """
    作为PDF下载失败后的fallback方法
    
    Args:
        nct_id: NCT ID
    
    Returns:
        结构化结果数据或None
    """
    logger.warning(f"⚠️ PDF download failed. Engaging ClinicalTrials.gov Protocol for {nct_id}...")
    
    client = ClinicalTrialsResultsClient()
    results = client.get_results(nct_id)
    
    if results and results.get('has_results'):
        logger.success(f"✅ Successfully retrieved structured results from ClinicalTrials.gov")
        return results
    else:
        logger.error(f"❌ No structured results available on ClinicalTrials.gov")
        return None
