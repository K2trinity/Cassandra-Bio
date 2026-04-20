"""
测试：验证生成的报告中是否包含开发公司名称

伪造数据流：
  药物: Zynficamab（完全虚构）
  开发公司: NovoBiogen Pharmaceuticals Inc.（完全虚构）

测试路径：
    1. 伪造 harvest / context 数据
  2. Mock LLM，令其返回包含公司名的章节 JSON
  3. 通过 DocumentComposer 组装并渲染 Markdown
  4. 断言公司名出现在最终报告中
"""

import sys
import os
import json
from pathlib import Path
from unittest.mock import MagicMock

# 把 Cassandra/ 加入 sys.path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# ──────────────────────────────────────────────
# 伪造常量
# ──────────────────────────────────────────────
FAKE_DRUG     = "Zynficamab"
FAKE_COMPANY  = "NovoBiogen Pharmaceuticals Inc."
FAKE_QUERY    = f"investigate {FAKE_DRUG} safety profile"

# ──────────────────────────────────────────────
# 伪造数据集
# ──────────────────────────────────────────────

FAKE_HARVEST_DATA = {
    "results": [
        {
            "nct_id": "NCT99887766",
            "title": f"Phase III Study of {FAKE_DRUG} in Advanced Lung Cancer",
            "sponsor": FAKE_COMPANY,
            "status": "TERMINATED",
            "phase": "Phase 3",
            "condition": "Non-Small Cell Lung Cancer"
        },
        {
            "nct_id": "NCT99887755",
            "title": f"Phase II Open-Label Study of {FAKE_DRUG}",
            "sponsor": FAKE_COMPANY,
            "status": "COMPLETED",
            "phase": "Phase 2",
            "condition": "Non-Small Cell Lung Cancer"
        }
    ]
}

FAKE_EVIDENCE_DATA = [
    {
        "source": "NCT99887766_supplement.pdf",
        "risk_level": "HIGH",
        "text": (
            f"{FAKE_COMPANY} reported that {FAKE_DRUG} failed to meet the primary endpoint "
            "of overall survival (HR=0.98, p=0.87). Supplementary Table S4 reveals a 34% "
            "dropout rate in the treatment arm, which was not disclosed in the main manuscript."
        )
    },
    {
        "source": "PMC_fake_123.pdf",
        "risk_level": "MEDIUM",
        "text": (
            f"Preclinical data from {FAKE_COMPANY}'s IND application showed off-target "
            "binding to cardiac voltage-gated channels at clinically relevant concentrations."
        )
    }
]

FAKE_EVIDENCE_TEXT = "\n\n".join(e["text"] for e in FAKE_EVIDENCE_DATA)


# ──────────────────────────────────────────────
# 伪造 LLM：返回预设的章节 JSON
# ──────────────────────────────────────────────

def _make_chapter_json(title: str, company: str, drug: str, detail: str) -> str:
    """生成一个包含公司名的章节 JSON 字符串（模拟 LLM 输出）"""
    data = {
        "title": title,
        "blocks": [
            {
                "type": "paragraph",
                "content": (
                    f"{drug} is an investigational monoclonal antibody developed by "
                    f"{company}. {detail}"
                )
            },
            {
                "type": "list",
                "content": [
                    f"Developer / Sponsor: {company}",
                    f"Drug Name: {drug}",
                    "Mechanism: PD-L1 checkpoint inhibitor (fictitious)",
                    "Current Stage: Phase III (TERMINATED)",
                    "Indication: Non-Small Cell Lung Cancer"
                ]
            },
            {
                "type": "callout",
                "content": (
                    f"⚠️ {company}'s Phase III trial NCT99887766 was terminated early "
                    "due to futility at interim analysis."
                )
            }
        ]
    }
    return json.dumps(data)


class FakeLLM:
    """
    模拟 LLM 客户端。
    无论传入什么提示词，都返回含公司名的预设章节 JSON。
    """

    model_name = "fake-gemini-pro"

    def invoke(self, system_prompt: str, user_prompt: str) -> str:
        # 从 user_prompt 中试图识别章节标题
        title = "Analysis"
        for marker in ["Drug Profile", "Executive Summary", "Scientific Rationale",
                        "Dark Data", "Risk Assessment", "Investment Recommendation"]:
            if marker.lower() in user_prompt.lower():
                title = marker
                break

        return _make_chapter_json(
            title=title,
            company=FAKE_COMPANY,
            drug=FAKE_DRUG,
            detail=(
                "The compound targets the PD-1/PD-L1 axis and was designed to overcome "
                "resistance to first-generation checkpoint inhibitors."
            )
        )


# ──────────────────────────────────────────────
# 主测试
# ──────────────────────────────────────────────

def run_test():
    print("=" * 60)
    print("TEST: Company name presence in segmented report")
    print(f"  Drug    : {FAKE_DRUG}")
    print(f"  Company : {FAKE_COMPANY}")
    print("=" * 60)

    # 1. 引入需要的模块
    from src.engines.report_engine.nodes import create_chapter_generation_node, create_word_budget_node
    from src.engines.report_engine.core import ChapterStorage, DocumentComposer

    # 2. 用 FakeLLM 替换真实 LLM
    fake_llm = FakeLLM()
    chapter_generator = create_chapter_generation_node(fake_llm)
    word_budget_node   = create_word_budget_node(total_target_words=3500)
    composer           = DocumentComposer()

    # 3. 定义与 write_report_segmented 相同的章节结构（含新增的 drug_profile）
    sections = [
        {
            "slug": "drug_profile",
            "title": "Drug Profile & Developer Overview",
            "outline": (
                f"Provide a structured overview of {FAKE_DRUG}. "
                f"MUST include developer company name: {FAKE_COMPANY}. "
                "Include mechanism of action, development stage, and market context."
            ),
            "order": 1
        },
        {
            "slug": "executive_summary",
            "title": "Executive Summary",
            "outline": "High-level overview of findings, key risks, and recommendation.",
            "order": 2
        },
        {
            "slug": "risk_scoring",
            "title": "Risk Assessment",
            "outline": "Quantitative risk scoring and investment implications.",
            "order": 3
        },
        {
            "slug": "final_recommendation",
            "title": "Investment Recommendation",
            "outline": "Final verdict and actionable recommendations.",
            "order": 4
        }
    ]

    # 4. 构建 generation_context（含公司名指令）
    generation_context = {
        "query": FAKE_QUERY,
        "compiled_context_text": FAKE_EVIDENCE_TEXT,
        "failed_count": 0,
        "total_files": 2,
        "risk_override": None,
        "analysis_status": "COMPLETE",
        "failed_files": [],
        "require_sponsor_company": True,
        "sponsor_company_instruction": (
            f"MANDATORY: Every section MUST explicitly name the developer/sponsor company "
            f"'{FAKE_COMPANY}'. Do NOT omit the company name."
        )
    }

    # 5. 分配字数预算
    word_allocations = word_budget_node.allocate_budgets(sections)

    # 6. 逐章节生成
    chapters = []
    for section in sections:
        target_words = word_allocations[section["slug"]]["target_words"]
        success, chapter, errors = chapter_generator.generate(
            section_title=section["title"],
            section_outline=section["outline"],
            generation_context=generation_context,
            target_words=target_words,
            max_attempts=2
        )
        if success and chapter:
            chapter.order = section["order"]
            chapters.append(chapter)
            print(f"  ✅ [{section['title']}] generated ({chapter.word_count()} words)")
        else:
            print(f"  ❌ [{section['title']}] FAILED: {errors}")

    # 7. 组装并渲染
    document = composer.build_document(
        chapters=chapters,
        title=f"Biomedical Due Diligence: {FAKE_DRUG}",
        query=FAKE_QUERY,
        subtitle="Investment Risk Analysis — FAKE DATA TEST",
        metadata={"analysis_status": "COMPLETE", "total_files": 2, "failed_files": 0}
    )
    markdown_output = composer.render_markdown(document)

    # 8. 保存临时报告供人工核查
    out_dir = ROOT / "scripts" / "dev_checks" / "_outputs"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / "company_name_test_report.md"
    out_file.write_text(markdown_output, encoding="utf-8")
    print(f"\n  📄 Report saved: {out_file}")

    # ──────────────────────────────────────────
    # 9. 断言：公司名必须出现在报告中
    # ──────────────────────────────────────────
    print("\n" + "-" * 60)
    print("ASSERTIONS")
    print("-" * 60)

    # 断言 1：公司名出现在 Markdown 正文中
    assert FAKE_COMPANY in markdown_output, (
        f"❌ FAIL: Company name '{FAKE_COMPANY}' NOT found in report!\n"
        f"   First 300 chars of report:\n{markdown_output[:300]}"
    )
    print(f"  ✅ PASS: '{FAKE_COMPANY}' found in rendered Markdown")

    # 断言 2：公司名出现在 drug_profile 章节
    drug_profile_chapter = next(
        (c for c in chapters if c.slug == "drug_profile-developer-overview"
         or "drug" in c.slug), None
    )
    if drug_profile_chapter:
        chapter_text = " ".join(
            (b.content if isinstance(b.content, str) else " ".join(b.content))
            for b in drug_profile_chapter.blocks
        )
        assert FAKE_COMPANY in chapter_text, (
            f"❌ FAIL: Company name not found in 'Drug Profile' chapter!\n"
            f"   Chapter text: {chapter_text[:300]}"
        )
        print(f"  ✅ PASS: '{FAKE_COMPANY}' found in 'Drug Profile' chapter")
    else:
        print("  ⚠️  WARN: drug_profile chapter not identified by slug for deep-check (skipped)")

    # 断言 3：公司名出现次数 >= 章节数（每章至少提一次）
    mention_count = markdown_output.count(FAKE_COMPANY)
    print(f"  ℹ️  Company name mentioned {mention_count} time(s) across {len(chapters)} chapters")
    assert mention_count >= len(chapters), (
        f"❌ FAIL: Company name appears only {mention_count} time(s), "
        f"expected at least {len(chapters)} (one per chapter)"
    )
    print(f"  ✅ PASS: Mention count ({mention_count}) >= chapter count ({len(chapters)})")

    # 断言 4：药物名也出现在报告中
    assert FAKE_DRUG in markdown_output, f"❌ FAIL: Drug name '{FAKE_DRUG}' NOT found!"
    print(f"  ✅ PASS: Drug name '{FAKE_DRUG}' found in report")

    print("\n" + "=" * 60)
    print("🎉 ALL ASSERTIONS PASSED — company name correctly present in report")
    print("=" * 60)
    print(f"\n📄 Full report preview (first 800 chars):\n")
    print(markdown_output[:800])
    print("\n...")


if __name__ == "__main__":
    run_test()
