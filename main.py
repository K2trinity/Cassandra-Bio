#!/usr/bin/env python
"""
Cassandra - Biomedical Research Workflow Platform
Main CLI Entry Point

This is the command-line interface for executing the Cassandra workflow.

Usage:
    python main.py "Analyze drug X safety concerns" [--pdfs path1.pdf path2.pdf]
    
Example:
    python main.py "Investigate pembrolizumab cardiotoxicity" --pdfs paper1.pdf paper2.pdf
    
    # Or run interactively:
    python main.py
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime
from loguru import logger
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logger
logger.remove()  # Remove default handler
logger.add(
    sys.stdout,
    colorize=True,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
)

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.agents.supervisor import run_cassandra_workflow


def print_banner():
    """Print the Cassandra banner."""
    banner = """
╔═══════════════════════════════════════════════════════════════════════════╗
║                                                                           ║
║                            CASSANDRA v1.0                                 ║
║                 Biomedical Research Workflow Platform                     ║
║                                                                           ║
║  Powered by:                                                              ║
║    • Google Gemini Pro (2M token context)                                 ║
║    • BioHarvestEngine (PubMed + ClinicalTrials.gov)                       ║
║    • LangGraph Orchestration                                              ║
║                                                                           ║
╚═══════════════════════════════════════════════════════════════════════════╝
"""
    print(banner)


def interactive_mode():
    """Run in interactive mode - prompt user for input."""
    print_banner()
    
    print("\n🔬 Welcome to Cassandra Interactive Mode\n")
    print("This tool runs a connected biomedical research analysis workflow.")
    print("It analyzes scientific literature and trial metadata to produce")
    print("a structured disease-oriented report.\n")
    
    # Get user query
    print("=" * 80)
    user_query = input("\n📋 Enter your research question:\n> ")
    
    if not user_query.strip():
        logger.error("❌ No query provided. Exiting.")
        sys.exit(1)
    
    # Get PDF paths (optional)
    print("\n📄 Enter PDF file paths to analyze (comma-separated, or press Enter to skip):")
    print("   Note: PDFs will also be auto-discovered from PubMed Central links")
    pdf_input = input("> ")
    
    pdf_paths = []
    if pdf_input.strip():
        pdf_paths = [p.strip() for p in pdf_input.split(",") if p.strip()]
        
        # Validate PDF paths
        invalid_paths = [p for p in pdf_paths if not Path(p).exists()]
        if invalid_paths:
            logger.warning(f"⚠️ Some PDFs not found: {invalid_paths}")
            confirm = input("Continue anyway? (y/n): ")
            if confirm.lower() != 'y':
                sys.exit(0)
    
    # Confirm execution
    print("\n" + "=" * 80)
    print("🚀 WORKFLOW SUMMARY")
    print("=" * 80)
    print(f"Query: {user_query}")
    print(f"Pre-loaded PDFs: {len(pdf_paths)}")
    print("\nWorkflow Steps:")
    print("  1. 🔬 BioHarvest: Search PubMed + ClinicalTrials.gov")
    print("  2. 🧩 Extension Handoff: Reserve insertion slots for future agents")
    print("  3. 📝 Report Writer: Generate structured final report")
    print("=" * 80)
    
    confirm = input("\nProceed with analysis? (y/n): ")
    if confirm.lower() != 'y':
        logger.info("Analysis cancelled by user.")
        sys.exit(0)
    
    # Run workflow
    return run_workflow(user_query, pdf_paths)


def run_workflow(user_query: str, pdf_paths: list = None):
    """
    Execute the Cassandra workflow.
    
    Args:
        user_query: Research question
        pdf_paths: Optional list of PDF file paths
    
    Returns:
        Final workflow state
    """
    start_time = datetime.now()
    
    try:
        # Execute workflow
        final_state = run_cassandra_workflow(user_query, pdf_paths)
        
        # Calculate duration
        duration = (datetime.now() - start_time).total_seconds()
        
        # Display results
        print("\n" + "=" * 80)
        print("✅ ANALYSIS COMPLETE")
        print("=" * 80)
        print(f"Duration: {duration:.1f} seconds")
        print(f"Status: {final_state.get('status', 'unknown')}")
        
        # Save report
        if final_state.get("final_report"):
            # Report is already saved by ReportWriterAgent
            logger.success("📄 Report saved to: final_reports/")
            
            # Offer to display preview
            preview = input("\nDisplay report preview? (y/n): ")
            if preview.lower() == 'y':
                print("\n" + "=" * 80)
                print("REPORT PREVIEW (First 1000 characters)")
                print("=" * 80)
                print(final_state["final_report"][:1000] + "...")
                print("\n[See full report in final_reports/ directory]")
        else:
            logger.warning("⚠️ No report generated")
        
        # Display errors if any
        if final_state.get("errors"):
            print("\n⚠️ Errors encountered during execution:")
            for error in final_state["errors"]:
                print(f"  - {error}")
        
        return final_state
        
    except KeyboardInterrupt:
        logger.warning("\n\n⚠️ Analysis interrupted by user (Ctrl+C)")
        sys.exit(1)
        
    except Exception as e:
        logger.error(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    """Main entry point."""
    
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="Cassandra - Biomedical Research Workflow Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode
  python main.py
  
  # Direct query with PDFs
  python main.py "Analyze pembrolizumab safety" --pdfs paper1.pdf paper2.pdf
  
  # Query without PDFs (will auto-discover from PubMed Central)
  python main.py "Investigate CAR-T therapy failures"
"""
    )
    
    parser.add_argument(
        "query",
        nargs="?",
        help="Research question or drug name to investigate"
    )
    
    parser.add_argument(
        "--pdfs",
        nargs="+",
        help="PDF file paths to analyze (optional)"
    )
    
    parser.add_argument(
        "--no-banner",
        action="store_true",
        help="Suppress banner display"
    )
    
    args = parser.parse_args()
    
    # Show banner
    if not args.no_banner:
        print_banner()
    
    # Interactive mode if no query provided
    if not args.query:
        interactive_mode()
    else:
        # Direct execution mode
        logger.info(f"🚀 Starting Cassandra workflow...")
        logger.info(f"📋 Query: {args.query}")
        
        if args.pdfs:
            logger.info(f"📄 Pre-loaded PDFs: {len(args.pdfs)}")
        
        run_workflow(args.query, args.pdfs)


if __name__ == "__main__":
    main()
