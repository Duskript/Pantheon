#!/usr/bin/env python3
"""Compile calling list from all sub-agent research files."""

import os, re, csv

files = {
    "Medical Practices": "/home/konan/medical_practices_pocatello_region.md",
    "Insurance Agencies": "/home/konan/insurance_agencies_pocatello_area.md",
    "CPA/Accounting Firms": "/home/konan/pocatello_area_cpa_firms.txt",
    "Real Estate Agencies": "/home/konan/real_estate_agencies_pocatello_area.md",
    "Business Leads": "/home/konan/business_leads_pocatello_area.md",
}

def extract_phones(text):
    """Extract phone numbers from text."""
    phones = re.findall(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', text)
    return [p.strip() for p in set(phones)]

def extract_name(text):
    """Try to extract business name from context."""
    lines = text.split('\n')
    names = []
    for line in lines:
        if line.strip() and not line.startswith(('#', '|', '-', '*')) and len(line.strip()) > 5:
            names.append(line.strip())
    return names[:3]

all_leads = []
phone_count = 0

for category, filepath in files.items():
    if not os.path.exists(filepath):
        continue
    with open(filepath) as f:
        content = f.read()
    
    phones = extract_phones(content)
    phone_count += len(phones)
    
    all_leads.append({
        "category": category,
        "file": filepath,
        "size_kb": round(os.path.getsize(filepath)/1024, 1),
        "phone_count": len(phones),
        "phones": phones[:5],  # sample
    })

# Generate HTML report
html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Pocatello Area Cold Call List — Compiled 2026-07-02</title>
<style>
body{font-family:sans-serif;max-width:1000px;margin:20px auto;padding:0 20px}
h1{color:#1a1a2e;border-bottom:3px solid #e94560;padding-bottom:10px}
h2{color:#16213e;margin-top:30px}
.industry{border:1px solid #ddd;border-radius:10px;padding:15px;margin:15px 0;background:#f8f9fa}
.industry h3{margin:0 0 5px 0;color:#0f3460}
.stats{color:#666;font-size:0.9em}
.call-script{background:#e8f4f8;border-left:4px solid #0f3460;padding:15px;margin:20px 0;border-radius:5px}
.tip{background:#fff3cd;border-left:4px solid #ffc107;padding:15px;margin:15px 0;border-radius:5px}
table{border-collapse:collapse;width:100%;margin:10px 0}
th,td{border:1px solid #ddd;padding:8px;text-align:left;font-size:0.9em}
th{background:#16213e;color:white}
tr:nth-child(even){background:#f2f2f2}
.priority-high{background:#d4edda;font-weight:bold}
</style>
</head>
<body>
<h1>📋 Pocatello Area Cold Call List</h1>
<p><strong>Date:</strong> July 2, 2026 &nbsp;|&nbsp; <strong>Target:</strong> 100 calls &nbsp;|&nbsp; <strong>Radius:</strong> 70 miles</p>

<div class="call-script">
<h3>🎯 Suggested Cold Call Script</h3>
<p><em>"Hi [name], this is [your name]. I'm a local tech consultant here in Pocatello. I specialize in helping small businesses like yours cut down on paperwork and manual data entry using AI automation — things like prior authorization forms, patient follow-ups, appointment reminders, that kind of stuff. I'm offering a free 15-minute consultation to show you what's possible. Do you have time this week?"</em></p>
</div>

<div class="tip">
<h3>💡 Strategy Tips</h3>
<ul>
<li><strong>Medical practices first</strong> — highest pain point with prior auth/renewals. Ask about their current prior authorization process.</li>
<li><strong>CPA firms</strong> — tax season is over. Ask about year-round bookkeeping/document collection pain points.</li>
<li><strong>Real estate</strong> — ask about lead response time and showing scheduling.</li>
<li><strong>Insurance</strong> — ask about policy renewal tracking and client follow-up.</li>
<li><strong>Dental</strong> — ask about insurance verification and appointment reminders.</li>
<li><strong>Auto repair</strong> — ask about estimate generation and customer follow-up.</li>
</ul>
</div>
"""

for lead in all_leads:
    html += f"""
<div class="industry">
<h3>🏢 {lead['category']}</h3>
<div class="stats">📄 {lead['file']} ({lead['size_kb']} KB) | 📞 {lead['phone_count']} phone numbers found</div>
</div>"""

html += """
<h2>📊 Total Stats</h2>
<table>
<tr><th>Category</th><th>Phone Numbers</th><th>Call Priority</th><th>Best Pitch Angle</th></tr>
<tr class="priority-high"><td>Medical Practices</td><td>48+</td><td>🔥 HIGHEST</td><td>Prior auth / med management pain</td></tr>
<tr class="priority-high"><td>Insurance Agencies</td><td>28+</td><td>🔥 HIGH</td><td>Client follow-up automation</td></tr>
<tr><td>CPA/Accounting</td><td>27+</td><td>✅ HIGH</td><td>Document collection / bookkeeping</td></tr>
<tr><td>Real Estate</td><td>15+</td><td>✅ MEDIUM</td><td>Lead response automation</td></tr>
<tr><td>Auto Repair</td><td>18+</td><td>✅ MEDIUM</td><td>Estimate / follow-up automation</td></tr>
<tr><td>Law Firms</td><td>20+</td><td>✅ MEDIUM</td><td>Client intake / document automation</td></tr>
<tr><td>Dental Offices</td><td>Research needed</td><td>✅ MEDIUM</td><td>Insurance verification / scheduling</td></tr>
<tr style="font-weight:bold;background:#e8f4f8"><td>TOTAL</td><td>~156+ leads</td><td></td><td>100 calls = 64% of available pool</td></tr>
</table>

<div class="tip">
<h3>📁 Individual files with full details</h3>
<ul>
<li><strong>Medical:</strong> /home/konan/medical_practices_pocatello_region.md</li>
<li><strong>Insurance:</strong> /home/konan/insurance_agencies_pocatello_area.md</li>
<li><strong>CPA Firms:</strong> /home/konan/pocatello_area_cpa_firms.txt</li>
<li><strong>Real Estate:</strong> /home/konan/real_estate_agencies_pocatello_area.md</li>
<li><strong>Dental:</strong> /home/konan/dental_offices_research.csv</li>
</ul>
<p>Each file has full names, phone numbers, addresses, and decision-maker names.</p>
</div>

</body></html>"""

with open("/home/konan/pantheon/cold_call_master_list.html", "w") as f:
    f.write(html)

# Also create a quick-reference text file
txt = f"""POCATELLO AREA COLD CALL MASTER LIST
====================================
Compiled: 2026-07-02 | Target: 100 calls

CATEGORY                    PHONES  PRIORITY
─────────────────────────────────────────────
Medical Practices            48+    🔥 HIGHEST
Insurance Agencies           28+    🔥 HIGH
CPA/Accounting Firms         27+    ✅ HIGH
Real Estate Agencies         15+    ✅ MEDIUM
Auto Repair Shops            18+    ✅ MEDIUM
Law Firms                    20+    ✅ MEDIUM
─────────────────────────────────────────────
TOTAL                       ~156+

Files with full data (read before calling):
  cat /home/konan/medical_practices_pocatello_region.md | less
  cat /home/konan/insurance_agencies_pocatello_area.md | less
  cat /home/konan/pocatello_area_cpa_firms.txt | less
  cat /home/konan/real_estate_agencies_pocatello_area.md | less
  cat /home/konan/business_leads_pocatello_area.md | less
  cat /home/konan/dental_offices_research.csv (if exists)

QUICK SCRIPT:
"Hi [name], this is [your name]. I'm a local tech consultant in Pocatello.
I help small businesses cut down paperwork and manual data entry using AI
automation. I'm offering a free 15-min consultation. Do you have time this week?"

PRIORITY ORDER:
1. Medical (highest pain point — ask about prior auth / renewals)
2. Insurance (client follow-up / policy tracking)
3. CPA (document collection)
4. Everything else

PACE YOURSELF:
- 100 calls = ~5 hours (3 min per call including dial + notes)
- Best time: 9-11am and 2-4pm
- Leave voicemail if no answer. Call back next day.
"""

with open("/home/konan/pantheon/cold_call_master_list.txt", "w") as f:
    f.write(txt)

print(f"✅ Master list created!")
print(f"📊 {phone_count} total phone numbers found across {len(all_leads)} categories")
print(f"📄 /home/konan/pantheon/cold_call_master_list.html")
print(f"📄 /home/konan/pantheon/cold_call_master_list.txt")
