"""
Neo4j Knowledge Graph Manager - Bio-Short-Seller

This module manages persistent storage of biomedical risk signals in a Neo4j graph database.

Schema:
- Nodes: Drug, Target, Risk, Source (PMC articles, NCT trials)
- Relationships: TARGETS, REPORTS_FAILURE, HAS_RISK

Usage:
    graph = GraphManager()
    graph.add_risk_signal(
        drug="Pembrolizumab",
        target="PD-1",
        source="NCT03456789",
        risk="Cardiotoxicity"
    )
    graph.close()
"""

import os
from typing import Optional, Dict, List
from loguru import logger

try:
    from neo4j import GraphDatabase
    from neo4j.exceptions import ServiceUnavailable, AuthError
    NEO4J_AVAILABLE = True
except ImportError:
    logger.warning("Neo4j driver not installed. Graph features disabled.")
    NEO4J_AVAILABLE = False


class GraphManager:
    """
    Neo4j Knowledge Graph Manager for Bio-Short-Seller.
    
    Manages persistent storage of:
    - Drug entities and their molecular targets
    - Clinical trial failures
    - Risk signals (toxicity, efficacy failures)
    - Source documents (papers, trials)
    
    Prevents duplicate analyses and enables cross-query insights.
    """
    
    def __init__(self):
        """
        Initialize connection to Neo4j database.
        
        Environment Variables:
            NEO4J_URI: Database URI (default: bolt://localhost:7687)
            NEO4J_USER: Database username (default: neo4j)
            NEO4J_PASSWORD: Database password (default: password)
        """
        if not NEO4J_AVAILABLE:
            logger.warning("Neo4j features disabled (driver not installed)")
            self.driver = None
            return
        
        # Load connection parameters
        self.uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = os.getenv("NEO4J_USER", "neo4j")
        self.password = os.getenv("NEO4J_PASSWORD", "password")
        
        # Initialize driver
        try:
            from neo4j import basic_auth
            self.driver = GraphDatabase.driver(
                self.uri,
                auth=basic_auth(self.user, self.password)
            )
            self.verify_connection()
            logger.success(f"✅ Connected to Neo4j Knowledge Graph at {self.uri}")
            
        except AuthError:
            logger.error(f"❌ Neo4j authentication failed for user '{self.user}'")
            self.driver = None
            
        except ServiceUnavailable:
            logger.warning(
                f"⚠️ Neo4j not available at {self.uri}. "
                "Graph features disabled. Start Neo4j or set NEO4J_URI."
            )
            self.driver = None
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to Neo4j: {e}")
            self.driver = None
    
    def verify_connection(self):
        """
        Verify database connectivity.
        
        Raises:
            Exception: If connection verification fails
        """
        if self.driver:
            self.driver.verify_connectivity()
    
    def close(self):
        """Close database connection."""
        if self.driver:
            self.driver.close()
            logger.info("Neo4j connection closed")
    
    def add_risk_signal(
        self,
        drug: str,
        target: str,
        source: str,
        risk: str,
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        Add a risk signal to the knowledge graph.
        
        Creates/merges nodes for drug, target, risk, and source,
        then establishes relationships between them.
        
        Args:
            drug: Drug/therapy name (e.g., "Pembrolizumab")
            target: Molecular target (e.g., "PD-1")
            source: Source identifier (e.g., "NCT03456789" or "PMC7654321")
            risk: Risk type (e.g., "Cardiotoxicity", "Efficacy Failure")
            metadata: Optional additional properties for the risk node
        
        Returns:
            True if successful, False if graph unavailable
        
        Example:
            >>> graph = GraphManager()
            >>> graph.add_risk_signal(
            ...     drug="Pembrolizumab",
            ...     target="PD-1",
            ...     source="NCT03456789",
            ...     risk="Cardiotoxicity",
            ...     metadata={"severity": "Grade 3+", "count": 8}
            ... )
        """
        if not self.driver:
            logger.debug("Graph unavailable, skipping risk signal storage")
            return False
        
        try:
            # Cypher query to MERGE nodes (avoid duplicates) and create relationships
            query = """
            MERGE (d:Drug {name: $drug})
            MERGE (t:Target {name: $target})
            MERGE (r:Risk {name: $risk})
            MERGE (s:Source {id: $source})
            
            MERGE (d)-[:TARGETS]->(t)
            MERGE (s)-[:REPORTS_FAILURE]->(d)
            MERGE (d)-[:HAS_RISK]->(r)
            
            SET r += $metadata
            
            RETURN d.name as drug, r.name as risk
            """
            
            with self.driver.session() as session:
                result = session.run(
                    query,
                    drug=drug,
                    target=target,
                    source=source,
                    risk=risk,
                    metadata=metadata or {}
                )
                
                # Consume result to ensure write committed
                record = result.single()
                
                logger.info(f"📊 Graph: {drug} → {risk} (Source: {source})")
                return True
                
        except Exception as e:
            logger.error(f"Failed to add risk signal to graph: {e}")
            return False
    
    def add_clinical_trial(
        self,
        nct_id: str,
        drug: str,
        status: str,
        phase: str,
        why_stopped: Optional[str] = None
    ) -> bool:
        """
        Add a clinical trial node to the graph.
        
        Args:
            nct_id: ClinicalTrials.gov identifier (e.g., "NCT03456789")
            drug: Drug being tested
            status: Trial status (e.g., "TERMINATED", "COMPLETED")
            phase: Trial phase (e.g., "Phase 2", "Phase 3")
            why_stopped: Termination reason (if applicable)
        
        Returns:
            True if successful, False if graph unavailable
        """
        if not self.driver:
            return False
        
        try:
            query = """
            MERGE (t:Trial {nct_id: $nct_id})
            MERGE (d:Drug {name: $drug})
            
            SET t.status = $status,
                t.phase = $phase,
                t.why_stopped = $why_stopped
            
            MERGE (t)-[:TESTS]->(d)
            
            RETURN t.nct_id
            """
            
            with self.driver.session() as session:
                session.run(
                    query,
                    nct_id=nct_id,
                    drug=drug,
                    status=status,
                    phase=phase,
                    why_stopped=why_stopped
                )
                
                logger.info(f"📊 Graph: Trial {nct_id} → {drug} ({status})")
                return True
                
        except Exception as e:
            logger.error(f"Failed to add trial to graph: {e}")
            return False
    
    def get_drug_risk_history(self, drug_name: str) -> List[Dict]:
        """
        Retrieve all risk signals for a drug from the graph.
        
        Args:
            drug_name: Drug name to query
        
        Returns:
            List of risk signal dictionaries with sources
        
        Example:
            >>> risks = graph.get_drug_risk_history("Pembrolizumab")
            >>> print(risks)
            [
                {"risk": "Cardiotoxicity", "source": "NCT03456789"},
                {"risk": "Immune Pneumonitis", "source": "PMC7654321"}
            ]
        """
        if not self.driver:
            return []
        
        try:
            query = """
            MATCH (d:Drug {name: $drug})-[:HAS_RISK]->(r:Risk)
            MATCH (s:Source)-[:REPORTS_FAILURE]->(d)
            RETURN r.name as risk, s.id as source
            ORDER BY r.name
            """
            
            with self.driver.session() as session:
                result = session.run(query, drug=drug_name)
                
                risks = [
                    {"risk": record["risk"], "source": record["source"]}
                    for record in result
                ]
                
                return risks
                
        except Exception as e:
            logger.error(f"Failed to query drug risk history: {e}")
            return []
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close connection."""
        self.close()


# Factory function for convenience
def create_graph_manager() -> GraphManager:
    """
    Create a GraphManager instance.
    
    Returns:
        GraphManager: Initialized graph manager (may be disabled if Neo4j unavailable)
    
    Example:
        >>> with create_graph_manager() as graph:
        ...     graph.add_risk_signal(...)
    """
    return GraphManager()
