"""
Cassandra Evidence Miner Agent - State Management
Defines all state data structures and operations for PDF document analysis workflow.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import json
from datetime import datetime


@dataclass
class Search:
    """Individual search result state for literature/evidence queries."""
    query: str = ""                    # Search query string
    url: str = ""                      # Result URL (paper link, database entry, etc.)
    title: str = ""                    # Result title
    content: str = ""                  # Retrieved content (abstract, excerpt, etc.)
    score: Optional[float] = None      # Relevance score from search API
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for serialization"""
        return {
            "query": self.query,
            "url": self.url,
            "title": self.title,
            "content": self.content,
            "score": self.score,
            "timestamp": self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Search":
        """Create Search object from dictionary data."""
        return cls(
            query=data.get("query", ""),
            url=data.get("url", ""),
            title=data.get("title", ""),
            content=data.get("content", ""),
            score=data.get("score"),
            timestamp=data.get("timestamp", datetime.now().isoformat())
        )


@dataclass
class Research:
    """Research process state for evidence mining and document analysis."""
    search_history: List[Search] = field(default_factory=list)     # Search history log
    latest_summary: str = ""                                       # Current section summary
    reflection_iteration: int = 0                                  # Reflection iteration count
    is_completed: bool = False                                     # Research completion flag
    
    def add_search(self, search: Search):
        """Add a search record to history."""
        self.search_history.append(search)
    
    def add_search_results(self, query: str, results: List[Dict[str, Any]]):
        """Batch add multiple search results from a single query."""
        for result in results:
            search = Search(
                query=query,
                url=result.get("url", ""),
                title=result.get("title", ""),
                content=result.get("content", ""),
                score=result.get("score")
            )
            self.add_search(search)
    
    def get_search_count(self) -> int:
        """Get total number of searches performed."""
        return len(self.search_history)
    
    def increment_reflection(self):
        """Increment reflection iteration counter."""
        self.reflection_iteration += 1
    
    def mark_completed(self):
        """Mark research as completed."""
        self.is_completed = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for serialization"""
        return {
            "search_history": [search.to_dict() for search in self.search_history],
            "latest_summary": self.latest_summary,
            "reflection_iteration": self.reflection_iteration,
            "is_completed": self.is_completed
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Research":
        """Create Research object from dictionary data."""
        search_history = [Search.from_dict(search_data) for search_data in data.get("search_history", [])]
        return cls(
            search_history=search_history,
            latest_summary=data.get("latest_summary", ""),
            reflection_iteration=data.get("reflection_iteration", 0),
            is_completed=data.get("is_completed", False)
        )


@dataclass
class Paragraph:
    """State of a single section in the evidence mining report."""
    title: str = ""                                                # Section title
    content: str = ""                                              # Expected content outline
    research: Research = field(default_factory=Research)          # Research progress tracker
    order: int = 0                                                 # Section order
    
    def is_completed(self) -> bool:
        """Check if section research is completed."""
        return self.research.is_completed and bool(self.research.latest_summary)
    
    def get_final_content(self) -> str:
        """Get final content (research summary or initial outline)."""
        return self.research.latest_summary or self.content
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for serialization"""
        return {
            "title": self.title,
            "content": self.content,
            "research": self.research.to_dict(),
            "order": self.order
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Paragraph":
        """Create Paragraph object from dictionary data."""
        research_data = data.get("research", {})
        research = Research.from_dict(research_data) if research_data else Research()
        
        return cls(
            title=data.get("title", ""),
            content=data.get("content", ""),
            research=research,
            order=data.get("order", 0)
        )


@dataclass
class State:
    """Complete evidence mining report state."""
    query: str = ""                                                # Original user query
    report_title: str = ""                                         # Report title
    paragraphs: List[Paragraph] = field(default_factory=list)     # Report sections
    final_report: str = ""                                         # Final compiled report
    is_completed: bool = False                                     # Completion flag
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def add_paragraph(self, title: str, content: str) -> int:
        """
        Add a new section to the report.
        
        Args:
            title: Section title
            content: Section content outline
            
        Returns:
            Section index
        """
        order = len(self.paragraphs)
        paragraph = Paragraph(title=title, content=content, order=order)
        self.paragraphs.append(paragraph)
        self.update_timestamp()
        return order
    
    def get_paragraph(self, index: int) -> Optional[Paragraph]:
        """Get section by index."""
        if 0 <= index < len(self.paragraphs):
            return self.paragraphs[index]
        return None
    
    def get_completed_paragraphs_count(self) -> int:
        """Get count of completed sections."""
        return sum(1 for p in self.paragraphs if p.is_completed())
    
    def get_total_paragraphs_count(self) -> int:
        """Get total section count."""
        return len(self.paragraphs)
    
    def is_all_paragraphs_completed(self) -> bool:
        """Check if all sections are completed."""
        return all(p.is_completed() for p in self.paragraphs) if self.paragraphs else False
    
    def mark_completed(self):
        """Mark entire report as completed."""
        self.is_completed = True
        self.update_timestamp()
    
    def update_timestamp(self):
        """Update modification timestamp."""
        self.updated_at = datetime.now().isoformat()
    
    def get_progress_summary(self) -> Dict[str, Any]:
        """Get report progress summary."""
        completed = self.get_completed_paragraphs_count()
        total = self.get_total_paragraphs_count()
        
        return {
            "total_paragraphs": total,
            "completed_paragraphs": completed,
            "progress_percentage": (completed / total * 100) if total > 0 else 0,
            "is_completed": self.is_completed,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for serialization"""
        return {
            "query": self.query,
            "report_title": self.report_title,
            "paragraphs": [p.to_dict() for p in self.paragraphs],
            "final_report": self.final_report,
            "is_completed": self.is_completed,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "State":
        """Create State object from dictionary data."""
        paragraphs = [Paragraph.from_dict(p_data) for p_data in data.get("paragraphs", [])]
        
        return cls(
            query=data.get("query", ""),
            report_title=data.get("report_title", ""),
            paragraphs=paragraphs,
            final_report=data.get("final_report", ""),
            is_completed=data.get("is_completed", False),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat())
        )
    
    @classmethod
    def from_json(cls, json_str: str) -> "State":
        """Create State object from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)
    
    def save_to_file(self, filepath: str):
        """Save state to file."""
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(self.to_json())
    
    @classmethod
    def load_from_file(cls, filepath: str) -> "State":
        """Load state from file."""
        with open(filepath, 'r', encoding='utf-8') as f:
            json_str = f.read()
        return cls.from_json(json_str)
