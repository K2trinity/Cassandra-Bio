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
                auth=basic_auth(self.user, self.password),
                connection_timeout=5,       # 5s max — avoids blocking analysis thread
                max_connection_lifetime=60, # recycle idle connections quickly
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
    
    def add_analysis_task(
        self,
        task_id: str,
        query: str,
        drug_name: str = "",
        created_at: str = ""
    ) -> bool:
        """Create/merge an Analysis task node."""
        if not self.driver:
            return False
        try:
            q = """
            MERGE (a:Analysis {task_id: $task_id})
            SET a.query     = $query,
                a.drug_name = $drug_name,
                a.created_at = $created_at
            RETURN a.task_id
            """
            with self.driver.session() as session:
                session.run(q, task_id=task_id, query=query,
                            drug_name=drug_name, created_at=created_at)
            logger.info(f"📊 Graph: Task node created [{task_id}]")
            return True
        except Exception as e:
            logger.error(f"Failed to add analysis task: {e}")
            return False

    def link_drug_to_task(self, task_id: str, drug: str) -> bool:
        """Link a Drug node to an Analysis task."""
        if not self.driver:
            return False
        try:
            q = """
            MERGE (a:Analysis {task_id: $task_id})
            MERGE (d:Drug {name: $drug})
            MERGE (a)-[:ANALYZED]->(d)
            """
            with self.driver.session() as session:
                session.run(q, task_id=task_id, drug=drug)
            return True
        except Exception as e:
            logger.error(f"Failed to link drug to task: {e}")
            return False

    def add_risk_signal_with_task(
        self,
        task_id: str,
        drug: str,
        risk: str,
        source: str = "",
        target: str = "",
        metadata: Optional[Dict] = None
    ) -> bool:
        """Add a risk signal linked to a specific analysis task."""
        if not self.driver:
            return False
        try:
            q = """
            MERGE (a:Analysis {task_id: $task_id})
            MERGE (d:Drug {name: $drug})
            MERGE (r:Risk {name: $risk})
            MERGE (a)-[:ANALYZED]->(d)
            MERGE (d)-[:HAS_RISK]->(r)
            MERGE (a)-[:FOUND_RISK]->(r)
            """
            params: Dict = dict(task_id=task_id, drug=drug, risk=risk)
            if source:
                q += "\nMERGE (s:Source {id: $source})\nMERGE (s)-[:REPORTS_FAILURE]->(d)\nMERGE (a)-[:USED_SOURCE]->(s)"
                params["source"] = source
            if target:
                q += "\nMERGE (t:Target {name: $tgt})\nMERGE (d)-[:TARGETS]->(t)"
                params["tgt"] = target
            if metadata:
                q += "\nSET r += $meta"
                params["meta"] = metadata
            with self.driver.session() as session:
                session.run(q, **params)
            logger.info(f"📊 Graph: [{task_id}] {drug} → {risk}")
            return True
        except Exception as e:
            logger.error(f"Failed to add risk signal with task: {e}")
            return False

    def add_rich_entities(
        self,
        task_id: str,
        drug: str,
        entities: List[Dict]
    ) -> int:
        """
        批量写入多类型实体节点到知识图谱，大幅增加关键词节点数量。

        entities 每项格式:
        {
          "label": "Disease"|"Mechanism"|"AdverseEvent"|"Endpoint"|"Gene"|"Pathway"|"Keyword",
          "name":  "<实体名称>",
          "rel":   "<关系类型>",      # 可选，默认按 label 自动推断
          "props": {...}              # 可选额外属性
        }
        Returns: 成功写入的节点数
        """
        if not self.driver:
            return 0

        # 关系类型映射
        _rel_map = {
            "Disease":      "TREATS",
            "Mechanism":    "HAS_MECHANISM",
            "AdverseEvent": "CAUSES_AE",
            "Endpoint":     "HAS_ENDPOINT",
            "Gene":         "TARGETS_GENE",
            "Pathway":      "AFFECTS_PATHWAY",
            "Keyword":      "ASSOCIATED_WITH",
            "Target":       "TARGETS",
        }

        written = 0
        with self.driver.session() as session:
            for ent in entities:
                label = ent.get("label", "Keyword")
                name  = (ent.get("name") or "").strip()[:200]
                if not name:
                    continue
                rel   = ent.get("rel") or _rel_map.get(label, "ASSOCIATED_WITH")
                props = ent.get("props") or {}
                try:
                    q = f"""
                    MERGE (a:Analysis {{task_id: $task_id}})
                    MERGE (d:Drug {{name: $drug}})
                    MERGE (a)-[:ANALYZED]->(d)
                    MERGE (e:{label} {{name: $name}})
                    MERGE (d)-[:{rel}]->(e)
                    MERGE (a)-[:FOUND_ENTITY]->(e)
                    """
                    params: Dict = dict(task_id=task_id, drug=drug, name=name)
                    if props:
                        q += "\nSET e += $props"
                        params["props"] = props
                    session.run(q, **params)
                    written += 1
                except Exception as e:
                    logger.warning(f"Graph entity write failed [{label}:{name}]: {e}")
        logger.info(f"📊 Graph: [{task_id}] +{written} rich entity nodes")
        return written

    def get_all_tasks(self) -> List[Dict]:
        """Return all Analysis task nodes ordered by created_at desc."""
        if not self.driver:
            return []
        try:
            q = """
            MATCH (a:Analysis)
            OPTIONAL MATCH (a)-[:ANALYZED]->(d:Drug)
            OPTIONAL MATCH (a)-[:FOUND_RISK]->(r:Risk)
            RETURN a.task_id   AS task_id,
                   a.query     AS query,
                   a.drug_name AS drug_name,
                   a.created_at AS created_at,
                   count(DISTINCT d) AS drug_count,
                   count(DISTINCT r) AS risk_count
            ORDER BY a.created_at DESC
            """
            with self.driver.session() as session:
                return [dict(rec) for rec in session.run(q)]
        except Exception as e:
            logger.error(f"Failed to get tasks: {e}")
            return []

    def get_task_graph(self, task_id: str) -> Dict:
        """Return nodes + links for a specific analysis task."""
        if not self.driver:
            return {"nodes": [], "links": []}
        try:
            q = """
            MATCH (a:Analysis {task_id: $task_id})
            OPTIONAL MATCH (a)-[r1]->(n1)
            OPTIONAL MATCH (n1)-[r2]->(n2)
            WITH collect(DISTINCT a) + collect(DISTINCT n1) + collect(DISTINCT n2) AS all_nodes,
                 collect(DISTINCT r1) + collect(DISTINCT r2) AS all_rels
            UNWIND all_nodes AS n
            WITH collect(DISTINCT n) AS nodes, all_rels
            UNWIND all_rels AS r
            RETURN nodes, collect(DISTINCT r) AS rels
            """
            nodes, links = [], []
            node_ids: set = set()
            with self.driver.session() as session:
                rec = session.run(q, task_id=task_id).single()
                if not rec:
                    return {"nodes": [], "links": []}
                for node in rec["nodes"]:
                    if node is None:
                        continue
                    nid = str(node.id)
                    if nid not in node_ids:
                        node_ids.add(nid)
                        lbl = list(node.labels)[0] if node.labels else "Unknown"
                        nodes.append({
                            "id": nid,
                            "label": lbl,
                            "name": node.get("name") or node.get("task_id") or node.get("id") or nid,
                            "properties": dict(node)
                        })
                for rel in rec["rels"]:
                    if rel is None:
                        continue
                    links.append({
                        "source": str(rel.start_node.id),
                        "target": str(rel.end_node.id),
                        "type": rel.type,
                        "properties": dict(rel)
                    })
            return {"nodes": nodes, "links": links}
        except Exception as e:
            logger.error(f"Failed to get task graph: {e}")
            return {"nodes": [], "links": []}

    def get_global_graph_data(self, limit: int = 200) -> Dict:
        """Return all nodes and relationships (capped at limit)."""
        if not self.driver:
            return {"nodes": [], "links": []}
        try:
            q = f"""
            MATCH (n)-[r]->(m)
            RETURN n, r, m
            LIMIT {limit}
            """
            nodes, links = [], []
            node_ids: set = set()
            with self.driver.session() as session:
                for rec in session.run(q):
                    for node in (rec["n"], rec["m"]):
                        nid = str(node.id)
                        if nid not in node_ids:
                            node_ids.add(nid)
                            lbl = list(node.labels)[0] if node.labels else "Unknown"
                            nodes.append({
                                "id": nid,
                                "label": lbl,
                                "name": node.get("name") or node.get("task_id") or node.get("id") or nid,
                                "properties": dict(node)
                            })
                    rel = rec["r"]
                    links.append({
                        "source": str(rel.start_node.id),
                        "target": str(rel.end_node.id),
                        "type": rel.type
                    })
            return {"nodes": nodes, "links": links}
        except Exception as e:
            logger.error(f"Failed to get global graph: {e}")
            return {"nodes": [], "links": []}

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
