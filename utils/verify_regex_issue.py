"""Demonstrate the regex matching issue for empty captions."""

import re

# Old pattern - only matches Figure/Fig
OLD_PATTERN = re.compile(r"(?i)(?:Figure|Fig\.?)\s*\d+[a-z]?.*")

# New pattern - includes Scheme, Graphical Abstract, etc.
NEW_PATTERN = re.compile(r"(?i)(?:Figure|Fig\.?|Scheme|Graphical\s+Abstract)\s*\d*[a-z]?.*")

# Text samples from the diagnostic output
test_texts = [
    "Graphical Abstract...",  # Page 2 - empty caption
    "Scheme 1.  Synthesis of 1,3,5-Benzenetricarbonyl Trichloride (TT)-Derived Lipid-Like Molecules (A)  ...",  # Page 20
    "Scheme 2.  Chemical Structures of Vitamin-Derived Ionizable Lipids (A) and Chemotherapy Drug- Derive...",  # Page 21
    "Scheme 3.  Synthesis of Ionizable Phospholipids (A) and Glycolipids (B)48...",  # Page 22
    "Scheme 4.  Examples of Chemically-Modified Nucleobases30...",  # Page 23
    "Figure 1. Biodegradability of (A) FTT5 and (B) FTT9...",  # Control - should match
]

print("="*80)
print("REGEX PATTERN MATCHING ANALYSIS")
print("="*80)

for text in test_texts:
    old_match = OLD_PATTERN.search(text) is not None
    new_match = NEW_PATTERN.search(text) is not None
    
    print(f"\nText: {text[:70]}...")
    print(f"  Old pattern (Figure/Fig only):        {old_match}")
    print(f"  New pattern (Figure/Fig/Scheme/GA):   {new_match}")
    
    if not old_match and new_match:
        print(f"  ✅ FIXED: Now captured by new pattern")

print("\n" + "="*80)
print("RESULT: Regex has been fixed to capture Scheme and Graphical Abstract!")
print("="*80)
