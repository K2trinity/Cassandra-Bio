# Bio-Short-Seller

**Biomedical Due Diligence Platform for Investment Research**

A forensic analysis system that mines scientific literature, clinical trials, and research papers to uncover buried negative results, failed trials, and potential fraud signals in biomedical research.

---

## 🔬 What is Bio-Short-Seller?

Bio-Short-Seller is an AI-powered due diligence platform that helps investors, analysts, and researchers identify hidden risks in biomedical research projects. It combines:

- **PubMed & ClinicalTrials.gov Harvesting** - Automated discovery of failed trials and adverse events
- **Dark Data Mining** - Extraction of negative results buried in supplementary materials
- **Forensic Image Analysis** - Detection of manipulated figures using AI vision
- **Knowledge Graph** - Persistent tracking of risk signals across drugs and targets
- **Investment-Grade Reports** - Structured markdown reports with risk scores

**Powered by:**
- Google Gemini 3.0 Pro (2M token context window)
- LangGraph (agent orchestration)
- Neo4j (knowledge graph database)

---

## 🚀 Quick Start

### Prerequisites
- Python 3.9+
- Google Gemini API key ([Get one here](https://ai.google.dev/))
- Neo4j database (optional, for knowledge graph features)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-org/bio-short-seller.git
   cd bio-short-seller
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env and add your GOOGLE_API_KEY
   ```

4. **Run your first analysis:**
   ```bash
   python main.py "Analyze pembrolizumab cardiotoxicity"
   ```

---

## 📖 Usage

### Interactive Mode
```bash
python main.py
# Follow the prompts to enter your research question
```

### Direct Query Mode
```bash
python main.py "Investigate CAR-T therapy failures" --pdfs paper1.pdf paper2.pdf
```

### Example Output
```
📊 Report Generation: Analyze pembrolizumab cardiotoxicity
=================================================================
✅ Harvested 18 papers/trials
✅ Mining Complete: 12 risk signals found
✅ Forensic Audit: 3 suspicious figures
✅ Report saved to: final_reports/pembrolizumab_20260201_143022.md

Recommendation: AVOID
Risk Score: 7.2/10
Confidence: 8.5/10
```

---

## 🏗️ Architecture

```
User Input
    ↓
BioHarvestEngine (PubMed + ClinicalTrials.gov)
    ↓
[Parallel Execution]
    ├→ EvidenceEngine (Dark Data Miner)
    └→ ForensicEngine (Image Forensics)
    ↓
GraphBuilder (Neo4j Knowledge Graph)
    ↓
ReportWriter (Investment Analysis)
    ↓
Final Markdown Report
```

### Core Engines

1. **BioHarvestEngine** (`BioHarvestEngine/`)
   - Searches PubMed for toxicity papers
   - Finds terminated/suspended trials on ClinicalTrials.gov
   - Extracts PMC full-text links

2. **EvidenceEngine** (`EvidenceEngine/`)
   - Reads full PDF texts (supplementary materials)
   - Mines for "data not shown", insignificant p-values
   - Extracts buried negative results

3. **ForensicEngine** (`ForensicEngine/`)
   - Analyzes scientific figures with Gemini Vision
   - Detects Western blot splicing, duplicated data
   - Flags suspicious image patterns

4. **ReportEngine** (`src/agents/report_writer.py`)
   - Synthesizes evidence into structured reports
   - Calculates weighted risk scores
   - Generates investment recommendations

---

## 🗂️ Project Structure

```
bio-short-seller/
├── main.py                     # CLI entry point
├── requirements.txt            # Python dependencies
├── .env.example               # Environment variable template
│
├── BioHarvestEngine/          # Literature & trial harvester
│   └── agent.py
├── EvidenceEngine/            # Dark data miner
│   └── agent.py
├── ForensicEngine/            # Image forensics
│   └── agent.py
│
├── src/
│   ├── agents/
│   │   ├── supervisor.py      # LangGraph orchestration
│   │   └── report_writer.py   # Report synthesis
│   ├── graph/
│   │   ├── state.py           # Workflow state
│   │   └── manager.py         # Neo4j integration
│   ├── llms/
│   │   └── gemini_client.py   # Unified LLM client
│   ├── tools/
│   │   ├── pubmed_client.py
│   │   ├── clinical_trials_client.py
│   │   └── pdf_processor.py
│   ├── prompts/               # Externalized prompts
│   │   ├── report_writer/
│   │   ├── evidence_miner/
│   │   ├── forensic_auditor/
│   │   └── bioharvest/
│   └── templates/
│       └── biomedical_report.md
│
├── final_reports/             # Generated markdown reports
├── logs/                      # Application logs
└── tests/                     # Unit tests
```

---

## ⚙️ Configuration

### Environment Variables

**Required:**
```bash
GOOGLE_API_KEY=your_gemini_api_key_here
```

**Optional (Engine Tuning):**
```bash
# Evidence Engine (long-context PDF analysis)
EVIDENCE_ENGINE_TEMPERATURE=0.4
EVIDENCE_ENGINE_MAX_TOKENS=8192

# Forensic Engine (image analysis)
FORENSIC_ENGINE_TEMPERATURE=0.2

# Report Engine (creative writing)
REPORT_ENGINE_TEMPERATURE=0.7
```

**Optional (Neo4j Knowledge Graph):**
```bash
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
```

---

## 📊 Output Format

Reports are generated in **Markdown** format with 7 sections:

1. **Executive Summary** - Go/No-Go recommendation with risk level
2. **Scientific Rationale** - Mechanism of action analysis
3. **Clinical Trial Audit** - Failed trials with termination reasons
4. **Dark Data Mining** - Buried negative results from supplements
5. **Forensic Image Audit** - Suspicious figure analysis
6. **Risk Graveyard** - Timeline of red flags
7. **Analyst Verdict** - Bull/Bear/Black Swan cases

### Example Excerpt
```markdown
## Clinical Trial Audit

NCT03456789 (Phase 2, Pembrolizumab + Chemotherapy): TERMINATED
- **Termination Reason:** "Unacceptable cardiotoxicity"
- **Evidence:** 8/30 subjects (27%) experienced Grade 3+ cardiac events [Trial: NCT03456789]
- **Red Flag:** Cardiac biomarker elevations dismissed as "not statistically significant" (p=0.14) despite clinical relevance [Source: PMC7654321, Supplementary Table 3]

**Risk Score:** 7.8/10
```

---

## 🧪 Development

### Running Tests
```bash
pytest tests/
```

### Code Quality
```bash
black src/ *.py
flake8 src/ *.py
```

### Docker Deployment
```bash
docker-compose up -d
```

---

## 🤝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Key Areas for Improvement
- [ ] Table extraction from PDF supplements (currently text-only)
- [ ] Multi-language support (currently English-focused)
- [ ] Real-time clinical trial monitoring
- [ ] Automated email alerts for new risk signals

---

## 📄 License

This project is licensed under the MIT License - see [LICENSE](LICENSE) for details.

---

## ⚠️ Disclaimer

Bio-Short-Seller is a **research tool** designed to surface publicly available data. It does not constitute financial or medical advice. Always conduct comprehensive due diligence before making investment decisions.

**Data Sources:**
- PubMed Central (PMC) - Public domain biomedical literature
- ClinicalTrials.gov - U.S. National Library of Medicine database
- All data analyzed is publicly accessible

---

## 🙏 Acknowledgments

- **Google Gemini Team** - For the 2M token context LLM
- **LangChain/LangGraph** - For agent orchestration framework
- **Neo4j** - For graph database technology
- **NCBI** - For PubMed API access

---

## 📞 Contact

- **Issues:** [GitHub Issues](https://github.com/your-org/bio-short-seller/issues)
- **Discussions:** [GitHub Discussions](https://github.com/your-org/bio-short-seller/discussions)
- **Email:** support@bio-short-seller.com

---

**Built with ❤️ for transparent biomedical research**
