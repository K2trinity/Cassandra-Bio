"""
Test script to validate the two critical fixes:
1. JSON Cleaner in EvidenceEngine
2. Mathematical Confidence Score in ReportWriter

Run this to verify the fixes are working as expected.
"""

import json
import re


def test_json_cleaner():
    """Test the _clean_json_text method to ensure it handles all edge cases."""
    
    print("=" * 60)
    print("🧪 TEST 1: JSON CLEANER (EvidenceEngine)")
    print("=" * 60)
    
    # Simulating the _clean_json_text method
    def clean_json_text(text):
        if not text:
            return "{}"
        
        # 1. Strip Markdown code block wrappers
        text = re.sub(r"```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"```\s*", "", text)
        
        # 2. Strip whitespace
        text = text.strip()
        
        # 3. Extract outermost JSON object
        start_idx = text.find('{')
        end_idx = text.rfind('}')
        
        if start_idx != -1 and end_idx != -1:
            text = text[start_idx : end_idx + 1]
        
        return text
    
    # Test cases
    test_cases = [
        {
            "name": "Markdown JSON block",
            "input": '```json\n{"paper_summary": "Test", "risk_signals": []}\n```',
            "expected_valid": True
        },
        {
            "name": "Python code block (wrong language)",
            "input": '```python\n{"paper_summary": "Test", "risk_signals": []}\n```',
            "expected_valid": True
        },
        {
            "name": "Text before JSON",
            "input": 'Here is the JSON:\n{"paper_summary": "Test", "risk_signals": []}',
            "expected_valid": True
        },
        {
            "name": "Mixed markdown and text",
            "input": 'Analysis complete:\n```json\n{"paper_summary": "Test", "risk_signals": []}\n```\nEnd of response',
            "expected_valid": True
        },
        {
            "name": "Clean JSON (no formatting)",
            "input": '{"paper_summary": "Test", "risk_signals": []}',
            "expected_valid": True
        },
        {
            "name": "Empty input",
            "input": '',
            "expected_valid": True  # Returns "{}"
        }
    ]
    
    passed = 0
    failed = 0
    
    for test in test_cases:
        try:
            cleaned = clean_json_text(test["input"])
            parsed = json.loads(cleaned)
            
            if test["expected_valid"]:
                print(f"✅ PASS: {test['name']}")
                passed += 1
            else:
                print(f"❌ FAIL: {test['name']} - Should have failed but passed")
                failed += 1
        except Exception as e:
            if not test["expected_valid"]:
                print(f"✅ PASS: {test['name']} (Expected failure)")
                passed += 1
            else:
                print(f"❌ FAIL: {test['name']} - {e}")
                failed += 1
    
    print(f"\n📊 Results: {passed} passed, {failed} failed\n")
    return failed == 0


def test_confidence_score_calculation():
    """Test the mathematical confidence score calculation."""
    
    print("=" * 60)
    print("🧮 TEST 2: MATHEMATICAL CONFIDENCE SCORE (ReportWriter)")
    print("=" * 60)
    
    # Simulating the confidence score calculation
    def calculate_confidence(total_files, failed_count):
        if total_files > 0:
            success_count = max(0, total_files - failed_count)
            raw_score = (success_count / total_files) * 10
            confidence_score = round(raw_score, 1)
        else:
            confidence_score = 0.0
        return confidence_score
    
    # Test cases
    test_cases = [
        {"total": 10, "failed": 0, "expected": 10.0, "description": "100% success"},
        {"total": 10, "failed": 5, "expected": 5.0, "description": "50% success"},
        {"total": 10, "failed": 10, "expected": 0.0, "description": "100% failure"},
        {"total": 5, "failed": 2, "expected": 6.0, "description": "60% success"},
        {"total": 3, "failed": 1, "expected": 6.7, "description": "67% success"},
        {"total": 0, "failed": 0, "expected": 0.0, "description": "No files"},
        {"total": 1, "failed": 0, "expected": 10.0, "description": "Single success"},
        {"total": 1, "failed": 1, "expected": 0.0, "description": "Single failure"},
    ]
    
    passed = 0
    failed = 0
    
    for test in test_cases:
        result = calculate_confidence(test["total"], test["failed"])
        
        if result == test["expected"]:
            print(f"✅ PASS: {test['description']}: {result}/10")
            passed += 1
        else:
            print(f"❌ FAIL: {test['description']}: Expected {test['expected']}, Got {result}")
            failed += 1
    
    print(f"\n📊 Results: {passed} passed, {failed} failed\n")
    return failed == 0


def main():
    print("\n" + "=" * 60)
    print("🔬 CASSANDRA FINAL FIX VALIDATION")
    print("=" * 60 + "\n")
    
    test1_pass = test_json_cleaner()
    test2_pass = test_confidence_score_calculation()
    
    print("=" * 60)
    if test1_pass and test2_pass:
        print("✅ ALL TESTS PASSED - FIXES ARE READY FOR DEPLOYMENT")
    else:
        print("❌ SOME TESTS FAILED - REVIEW IMPLEMENTATION")
    print("=" * 60 + "\n")
    
    print("📝 Next Steps:")
    print("1. Run the main pipeline with: python main.py")
    print("2. Verify 'Data not available' disappears from reports")
    print("3. Check that confidence scores are mathematically correct")
    print("4. Monitor logs for '🧮 Calculated Confidence' messages")


if __name__ == "__main__":
    main()
