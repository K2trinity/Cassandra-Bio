# 📄 PDF Generation Setup Guide

## Overview
Cassandra now generates **professional PDF reports** alongside Markdown files. The new workflow:

1. ✅ **On-Screen Display**: Full Markdown report rendered in the browser with collapsible viewer
2. ✅ **PDF Download**: One-click download of beautifully formatted PDF reports
3. ✅ **Automatic Fallback**: If PDF generation fails, Markdown is still available

---

## 🔧 Installation Steps

### Step 1: Install Python Dependencies

```bash
pip install markdown pdfkit
```

**What these do:**
- `markdown`: Converts Markdown → HTML with support for tables, code blocks, and extensions
- `pdfkit`: Python wrapper for `wkhtmltopdf` to convert HTML → PDF

---

### Step 2: Install wkhtmltopdf (System Dependency)

`wkhtmltopdf` is the underlying PDF rendering engine. Install it based on your OS:

#### **Windows**
1. Download from: https://wkhtmltopdf.org/downloads.html
2. Run the installer (choose default installation path: `C:\Program Files\wkhtmltopdf\`)
3. **Add to PATH** (Important!):
   - Right-click "This PC" → Properties → Advanced System Settings
   - Click "Environment Variables"
   - Under "System Variables", find `Path` and click "Edit"
   - Add: `C:\Program Files\wkhtmltopdf\bin`
4. Verify installation:
   ```bash
   wkhtmltopdf --version
   ```
   Expected output: `wkhtmltopdf 0.12.6 (with patched qt)`

#### **macOS**
```bash
brew install wkhtmltopdf
```

#### **Linux (Ubuntu/Debian)**
```bash
sudo apt-get update
sudo apt-get install wkhtmltopdf
```

---

## ✅ Verification

Run this test to confirm everything works:

```python
# test_pdf_generation.py
import pdfkit
import markdown

# Test Markdown → HTML
md_text = "# Test Report\n\n**Bold text** and *italic text*."
html = markdown.markdown(md_text)
print("✅ Markdown conversion successful")

# Test HTML → PDF
pdfkit.from_string(html, 'test_output.pdf')
print("✅ PDF generation successful! Check test_output.pdf")
```

Run:
```bash
python test_pdf_generation.py
```

---

## 🎨 PDF Styling Features

The generated PDFs include:

### Professional Typography
- **Font**: Georgia (serif) for body text, Times New Roman fallback
- **Size**: 11pt body text with hierarchical headings (24pt → 18pt → 14pt)
- **Line Height**: 1.6 for optimal readability
- **Justification**: Full text justification for academic aesthetic

### Visual Elements
- **Color Scheme**: Dark headers (#1a252f) with blue accents (#3498db)
- **Borders**: Clean separators for h1/h2 headings
- **Code Blocks**: Gray background (#f8f9fa) with left border accent
- **Tables**: Alternating row colors with professional header styling
- **Blockquotes**: Italic text with left border and padding

### Layout
- **Page Size**: A4 (210mm × 297mm)
- **Margins**: 2.5cm on all sides
- **Max Width**: 800px content area for optimal line length
- **Page Breaks**: Smart handling of long content

---

## 📂 Output Files

After analysis, you'll find in `final_reports/`:

```
final_reports/
├── pembrolizumab_20260202_123456.md   # Markdown source
└── pembrolizumab_20260202_123456.pdf  # Formatted PDF
```

---

## 🔄 Workflow Changes

### Before (Old Workflow)
```
Analysis → Markdown → Extract 1200 chars → Display snippet
```

### After (New Workflow)
```
Analysis → Markdown → Full text to frontend
                   ↓
                PDF generation → Download button
```

### User Experience
1. **Intelligence Card**: Shows risk assessment with terminal aesthetic
2. **Toggle Viewer**: Click "📄 View Complete Report" to expand full report
3. **Download PDF**: Click "Download PDF Report" for formatted file

---

## 🐛 Troubleshooting

### Error: `OSError: wkhtmltopdf reported an error`

**Cause**: wkhtmltopdf not in system PATH

**Fix**:
1. Find wkhtmltopdf installation:
   - Windows: `C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe`
   - macOS: `/usr/local/bin/wkhtmltopdf`
   - Linux: `/usr/bin/wkhtmltopdf`

2. Set path explicitly in code:
   ```python
   import pdfkit
   config = pdfkit.configuration(wkhtmltopdf='/path/to/wkhtmltopdf')
   pdfkit.from_string(html, 'output.pdf', configuration=config)
   ```

---

### Error: `ImportError: No module named 'markdown'`

**Fix**: Install dependencies
```bash
pip install markdown pdfkit
```

---

### PDF Generation Fails but Analysis Completes

**Behavior**: You'll see this warning in logs:
```
⚠️ PDF conversion failed, Markdown-only output available
💡 Install with: pip install markdown pdfkit
💡 Ensure wkhtmltopdf is installed
```

**Impact**: No PDF file generated, but Markdown report still accessible

**Fix**: Follow installation steps above, then re-run analysis

---

## 🔒 Security Notes

- **Local File Access**: PDFs are generated server-side with `enable-local-file-access` flag
- **No External Requests**: All conversion happens offline
- **Sanitization**: Markdown content is rendered as HTML without script execution

---

## 🎯 Testing PDF Generation

Run a test analysis to verify the full pipeline:

```bash
# Start Cassandra
python app.py

# Navigate to http://localhost:5000
# Enter query: "Analyze pembrolizumab cardiotoxicity"
# Wait for completion
# Check: final_reports/ directory should have both .md and .pdf files
```

Expected logs:
```
[Step E] Saving report...
✅ Markdown saved: final_reports/pembrolizumab_20260202_123456.md
[Step F] Converting to PDF...
✅ PDF saved: final_reports/pembrolizumab_20260202_123456.pdf
```

---

## 📚 References

- **wkhtmltopdf Documentation**: https://wkhtmltopdf.org/usage/wkhtmltopdf.txt
- **Python Markdown**: https://python-markdown.github.io/
- **PDFKit**: https://github.com/JazzCore/python-pdfkit

---

## 🚀 Next Steps

Once setup is complete:

1. Run `pip install markdown pdfkit`
2. Install wkhtmltopdf for your OS
3. Verify with test script
4. Run Cassandra analysis
5. Download professional PDF reports! 🎉
