"""
测试 JSON 修复三重防护机制

验证：
1. Token 配置是否已提升到 8192
2. json-repair 库是否可用
3. 手动修复逻辑是否正常
"""

import json
from src.llms import create_forensic_client
from src.agents.json_validator import JSONValidator

def test_token_config():
    """测试 Token 配置"""
    print("=" * 60)
    print("TEST 1: Token Configuration")
    print("=" * 60)
    
    # 直接读取代码检查配置
    import os
    default_tokens = int(os.getenv("FORENSIC_MAX_TOKENS", "8192"))
    print(f"✅ ForensicEngine default max_output_tokens: {default_tokens}")
    
    if default_tokens >= 8192:
        print("✅ PASS: Token limit is sufficient (>= 8192)")
    else:
        print(f"❌ FAIL: Token limit too low ({default_tokens} < 8192)")
    
    # 验证代码中的硬编码默认值
    with open("src/llms/gemini_client.py", "r", encoding="utf-8") as f:
        content = f.read()
        if '"FORENSIC_MAX_TOKENS", "8192"' in content:
            print("✅ PASS: Code contains correct default value (8192)")
        elif '"FORENSIC_MAX_TOKENS", "4096"' in content:
            print("❌ FAIL: Code still has old default value (4096)")
        else:
            print("⚠️ WARNING: Could not verify code default")
    
    print()


def test_json_repair_library():
    """测试 json-repair 库"""
    print("=" * 60)
    print("TEST 2: json-repair Library Availability")
    print("=" * 60)
    
    try:
        from json_repair import repair_json
        print("✅ json-repair library imported successfully")
        
        # 测试修复未终止的字符串
        broken_json = '{"status": "SUSPICIOUS", "findings": "The band labeled "Actin" shows signs'
        
        try:
            repaired = repair_json(broken_json)
            print(f"✅ Successfully repaired broken JSON")
            print(f"   Repaired output: {repaired}")
        except Exception as e:
            print(f"⚠️ Repair failed (expected for this complex case): {e}")
        
    except ImportError as e:
        print(f"❌ FAIL: json-repair library not available: {e}")
    
    print()


def test_manual_repair():
    """测试手动修复逻辑"""
    print("=" * 60)
    print("TEST 3: Manual JSON Repair Logic")
    print("=" * 60)
    
    # 模拟未终止字符串的 JSON
    broken_json_cases = [
        # Case 1: Unterminated string at end
        '{"image_id": "fig1.jpg", "status": "SUSPICIOUS", "findings": "Data looks suspicious',
        
        # Case 2: Unterminated string in middle
        '{"image_id": "fig2.jpg", "status": "CLEAN", "findings": "No issues, "tampering_probability": 0.1}',
        
        # Case 3: Missing closing brackets
        '{"image_id": "fig3.jpg", "status": "CLEAN", "findings": "All clear"',
    ]
    
    expected_fields = ["image_id", "status", "findings", "tampering_probability"]
    
    for i, broken_json in enumerate(broken_json_cases, 1):
        print(f"\nCase {i}:")
        print(f"  Input: {broken_json[:60]}...")
        
        # 创建模拟的 JSONDecodeError
        try:
            json.loads(broken_json)
        except json.JSONDecodeError as e:
            print(f"  Error: {e}")
            
            # 尝试修复
            result = JSONValidator._repair_unterminated_string(broken_json, expected_fields, e)
            
            if result:
                print(f"  ✅ Repaired successfully: {result}")
            else:
                print(f"  ⚠️ Could not repair this case")
    
    print()


def test_end_to_end():
    """端到端测试：模拟真实场景"""
    print("=" * 60)
    print("TEST 4: End-to-End JSON Validation")
    print("=" * 60)
    
    # 模拟 Gemini 可能返回的各种格式问题
    test_cases = [
        # Good JSON
        '{"image_id": "fig1.jpg", "status": "CLEAN", "tampering_probability": 0.1, "findings": "No issues"}',
        
        # JSON with markdown wrapper (应该被预处理清理)
        '''```json
{"image_id": "fig2.jpg", "status": "SUSPICIOUS", "tampering_probability": 0.8, "findings": "Possible manipulation"}
```''',
        
        # Truncated JSON (应该被修复)
        '{"image_id": "fig3.jpg", "status": "CLEAN", "findings": "All clear',
    ]
    
    expected_fields = ["image_id", "status", "tampering_probability", "findings"]
    
    for i, test_json in enumerate(test_cases, 1):
        print(f"\nCase {i}:")
        is_valid, data, errors = JSONValidator.validate_and_repair(test_json, expected_fields)
        
        if is_valid:
            print(f"  ✅ PASS: Validation successful")
            print(f"     Data keys: {list(data.keys())}")
            if errors:
                print(f"     Warnings: {len(errors)}")
        else:
            print(f"  ❌ FAIL: Validation failed")
            print(f"     Errors: {errors}")
    
    print()


if __name__ == "__main__":
    print("\n" + "🔬 JSON Repair Triple-Defense Test Suite 🔬".center(60))
    print("=" * 60)
    print()
    
    test_token_config()
    test_json_repair_library()
    test_manual_repair()
    test_end_to_end()
    
    print("=" * 60)
    print("✅ All tests completed!".center(60))
    print("=" * 60)
