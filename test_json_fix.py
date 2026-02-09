"""测试JSON修复功能"""
import sys
sys.path.insert(0, r'f:\Visual Studio Code\Cassandra')

from src.agents.json_validator import JSONValidator

# 测试案例1: 无引号属性名
test_case_1 = """{
  compound_name: "Test Drug",
  moa_description: "This is a test",
  target_description: "Test target"
}"""

print("=" * 60)
print("Test Case 1: Unquoted property names")
print("=" * 60)
print("Input:", test_case_1[:100])

is_valid, data, errors = JSONValidator.validate_and_repair(
    json_text=test_case_1,
    expected_fields=['compound_name', 'moa_description', 'target_description']
)

print(f"\n✅ Valid: {is_valid}")
if data:
    print("✅ Parsed data:")
    for k, v in data.items():
        print(f"  - {k}: {v}")
else:
    print("❌ Failed to parse")
if errors:
    print(f"⚠️ Errors: {errors}")

# 测试案例2: Markdown包裹
test_case_2 = """```json
{
  "compound_name": "Test Drug 2",
  "moa_description": "Another test"
}
```"""

print("\n" + "=" * 60)
print("Test Case 2: Markdown wrapped JSON")
print("=" * 60)
print("Input:", test_case_2[:100])

is_valid, data, errors = JSONValidator.validate_and_repair(
    json_text=test_case_2,
    expected_fields=['compound_name', 'moa_description']
)

print(f"\n✅ Valid: {is_valid}")
if data:
    print("✅ Parsed data:")
    for k, v in data.items():
        print(f"  - {k}: {v}")
else:
    print("❌ Failed to parse")

# 测试案例3: 混合问题
test_case_3 = """```json
{
  compound_name: "Test Drug 3",
  moa_description: "Test with issues",
  missing_field_test: "should be filled"
}"""

print("\n" + "=" * 60)
print("Test Case 3: Mixed issues (markdown + unquoted)")
print("=" * 60)
print("Input:", test_case_3[:100])

is_valid, data, errors = JSONValidator.validate_and_repair(
    json_text=test_case_3,
    expected_fields=['compound_name', 'moa_description', 'target_description']
)

print(f"\n✅ Valid: {is_valid}")
if data:
    print("✅ Parsed data:")
    for k, v in data.items():
        print(f"  - {k}: {v}")
else:
    print("❌ Failed to parse")
if errors:
    print(f"⚠️ Errors: {errors}")

print("\n" + "=" * 60)
print("All tests completed!")
print("=" * 60)
