import sqlite3
import json
import os

conn = sqlite3.connect('db.sqlite3')
c = conn.cursor()

# Check images
c.execute("SELECT COUNT(*) FROM questions_question WHERE section_id IN (542,543,544) AND image != '' AND image IS NOT NULL")
print('Questions with images:', c.fetchone())
c.execute("SELECT COUNT(*) FROM questions_option WHERE question_id IN (SELECT id FROM questions_question WHERE section_id IN (542,543,544)) AND image != '' AND image IS NOT NULL")
print('Options with images:', c.fetchone())

# Get test info
c.execute("SELECT id, name, duration_seconds FROM testseries_test WHERE id=130")
test = c.fetchone()
test_id, test_name, duration = test
hours = duration // 3600
minutes = (duration % 3600) // 60

# Get sections
c.execute("SELECT id, name, [order], marks_per_question, negative_marks_per_question FROM testseries_section WHERE test_id=130 ORDER BY [order]")
sections = c.fetchall()

# Build full data structure
sections_data = []
for sec_id, sec_name, sec_order, mpq, nmpq in sections:
    c.execute("SELECT id, text, image, correct_option_ids, explanation FROM questions_question WHERE section_id=? AND is_active=1 ORDER BY id", (sec_id,))
    questions = c.fetchall()
    
    q_list = []
    for q_id, q_text, q_image, correct_ids_json, explanation in questions:
        correct_ids = json.loads(correct_ids_json) if correct_ids_json else []
        
        c2 = conn.cursor()
        c2.execute("SELECT id, text, image, is_correct, [order] FROM questions_option WHERE question_id=? ORDER BY [order]", (q_id,))
        options = c2.fetchall()
        
        q_list.append({
            'id': q_id,
            'text': q_text,
            'image': q_image,
            'correct_ids': correct_ids,
            'explanation': explanation,
            'options': [{'id': o[0], 'text': o[1], 'image': o[2], 'is_correct': bool(o[3]), 'order': o[4]} for o in options]
        })
    
    sections_data.append({
        'id': sec_id,
        'name': sec_name,
        'order': sec_order,
        'mpq': mpq,
        'nmpq': nmpq,
        'questions': q_list
    })

# Generate HTML
option_labels = ['A', 'B', 'C', 'D', 'E', 'F']

html_parts = []
html_parts.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{test_name} - Question Paper</title>
<script>
MathJax = {{
  tex: {{
    inlineMath: [['\\\\(', '\\\\)'], ['$', '$']],
    displayMath: [['\\\\[', '\\\\]'], ['$$', '$$']],
    packages: {{'[+]': ['ams']}}
  }},
  options: {{
    skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre']
  }}
}};
</script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js" crossorigin="anonymous"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  
  body {{
    font-family: 'Times New Roman', Times, serif;
    font-size: 13px;
    color: #000;
    background: #fff;
    padding: 20px;
    line-height: 1.5;
  }}

  /* ---- Header ---- */
  .header {{
    text-align: center;
    border: 2px solid #000;
    padding: 12px 20px;
    margin-bottom: 20px;
  }}
  .header h1 {{
    font-size: 22px;
    font-weight: bold;
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-bottom: 4px;
  }}
  .header .meta {{
    font-size: 12px;
    display: flex;
    justify-content: center;
    gap: 40px;
    margin-top: 6px;
  }}
  .header .meta span {{
    font-weight: bold;
  }}

  /* ---- Answer Key Note ---- */
  .answer-key-badge {{
    display: inline-block;
    background: #1a1a2e;
    color: #fff;
    padding: 4px 14px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 1px;
    margin-bottom: 18px;
  }}

  /* ---- Section Header ---- */
  .section-header {{
    background: #1a1a2e;
    color: #fff;
    padding: 8px 16px;
    margin: 24px 0 12px 0;
    font-size: 15px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 1px;
    page-break-before: always;
  }}
  .section-header:first-of-type {{
    page-break-before: avoid;
  }}
  .section-meta {{
    font-size: 11px;
    color: #555;
    margin-bottom: 14px;
    padding-left: 2px;
  }}

  /* ---- Question Block ---- */
  .question-block {{
    margin-bottom: 16px;
    padding: 10px 12px;
    border: 1px solid #ddd;
    border-radius: 4px;
    page-break-inside: avoid;
  }}
  .question-block:hover {{
    background: #fafafa;
  }}

  .question-header {{
    display: flex;
    gap: 10px;
    align-items: flex-start;
    margin-bottom: 8px;
  }}
  .q-number {{
    font-weight: bold;
    font-size: 13px;
    min-width: 28px;
    color: #1a1a2e;
  }}
  .q-text {{
    flex: 1;
    font-size: 13px;
  }}

  /* ---- Options ---- */
  .options-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 5px 20px;
    margin-left: 38px;
    margin-top: 6px;
  }}
  .option-item {{
    display: flex;
    align-items: flex-start;
    gap: 6px;
    padding: 3px 6px;
    border-radius: 3px;
    font-size: 12.5px;
  }}
  .option-item.correct {{
    background: #e8f5e9;
    border: 1px solid #4caf50;
    border-radius: 4px;
    font-weight: bold;
  }}
  .option-label {{
    font-weight: bold;
    min-width: 18px;
    font-size: 12.5px;
  }}
  .option-label.correct-label {{
    color: #2e7d32;
  }}
  .correct-tick {{
    color: #2e7d32;
    font-size: 13px;
    margin-left: 2px;
  }}

  /* ---- Explanation ---- */
  .explanation {{
    margin-left: 38px;
    margin-top: 8px;
    padding: 6px 10px;
    background: #fff8e1;
    border-left: 3px solid #ffc107;
    font-size: 12px;
    color: #555;
    border-radius: 0 4px 4px 0;
  }}
  .explanation-label {{
    font-weight: bold;
    color: #e65100;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 2px;
  }}

  /* ---- Print Styles ---- */
  @media print {{
    body {{ padding: 10px; font-size: 12px; }}
    .section-header {{
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    .option-item.correct {{
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    .question-block {{ border: 1px solid #ccc; }}
    @page {{
      margin: 15mm 12mm;
      size: A4;
    }}
  }}
</style>
</head>
<body>

<div class="header">
  <h1>{test_name}</h1>
  <div class="meta">
    <div>Total Questions: <span>{sum(len(s['questions']) for s in sections_data)}</span></div>
    <div>Duration: <span>{hours}h {minutes}m</span></div>
    <div>Sections: <span>{len(sections_data)}</span></div>
  </div>
</div>

<div style="text-align:center;">
  <div class="answer-key-badge">&#10003; ANSWER KEY INCLUDED</div>
</div>
""")

q_global = 1
for sec in sections_data:
    mpq_text = f"Marks per question: {sec['mpq']}" if sec['mpq'] else ""
    nmpq_text = f" | Negative marks: {sec['nmpq']}" if sec['nmpq'] else ""
    
    html_parts.append(f"""
<div class="section-header">{sec['name']} &nbsp; ({len(sec['questions'])} Questions)</div>
{"<div class='section-meta'>" + mpq_text + nmpq_text + "</div>" if mpq_text else ""}
""")
    
    for q in sec['questions']:
        opts_html = ""
        for i, opt in enumerate(q['options']):
            label = option_labels[i] if i < len(option_labels) else str(i+1)
            correct_class = ' correct' if opt['is_correct'] else ''
            correct_label_class = ' correct-label' if opt['is_correct'] else ''
            tick = ' <span class="correct-tick">&#10003;</span>' if opt['is_correct'] else ''
            
            opt_text = opt['text']
            if opt['image']:
                img_url = f"media_transfer/{opt['image']}" if not opt['image'].startswith('http') else opt['image']
                opt_text += f'<br><img src="{img_url}" style="max-height:60px; max-width:200px; margin-top:4px;">'
            
            opts_html += f"""<div class="option-item{correct_class}">
              <span class="option-label{correct_label_class}">{label}.</span>
              <span>{opt_text}{tick}</span>
            </div>"""
        
        q_text = q['text']
        if q['image']:
            img_url = f"media_transfer/{q['image']}" if not q['image'].startswith('http') else q['image']
            q_text += f'<br><img src="{img_url}" style="max-height:120px; max-width:100%; margin-top:6px;">'
        
        explanation_html = ""
        if q['explanation'] and q['explanation'].strip():
            explanation_html = f"""
        <div class="explanation">
          <div class="explanation-label">Solution</div>
          {q['explanation']}
        </div>"""
        
        html_parts.append(f"""
<div class="question-block">
  <div class="question-header">
    <span class="q-number">Q{q_global}.</span>
    <span class="q-text">{q_text}</span>
  </div>
  <div class="options-grid">{opts_html}</div>{explanation_html}
</div>""")
        q_global += 1

html_parts.append("""
</body>
</html>
""")

output_path = 'test_130_paper.html'
with open(output_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(html_parts))

print(f"Generated: {output_path}")
print(f"Total questions: {q_global - 1}")
conn.close()
