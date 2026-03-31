#!/usr/bin/env python3
"""
analyse_readability.py — Analyse all Markdown files in a directory for
readability and accessibility, then generate a comprehensive HTML report
with per-document scores, recommendations, and a site-wide summary.

Each document is reviewed by configurable reviewer personas (loaded from
personas.json), each applying their own readability thresholds and
domain-specific checks.

Usage:
    python analyse_readability.py [--input-dir DIR] [--output FILE] [--personas FILE]

Reads YAML frontmatter to determine the target audience for each document
and adjusts scoring thresholds accordingly.
"""

import re
import sys
import math
import yaml
import json
import argparse
from pathlib import Path
from datetime import date
from collections import Counter


# ── Audience profiles ─────────────────────────────────────────

AUDIENCE_PROFILES = {
    "clinical professionals": {
        "label": "Clinical Professionals",
        "max_grade": 16, "ideal_grade": 12,
        "max_fog": 18, "ideal_fog": 14,
        "max_aws": 30, "ideal_aws": 20,
        "domain_words": {
            "consultation", "consultations", "practitioner", "practitioners",
            "questionnaire", "questionnaires", "healthcare", "organisation",
            "organisations", "notifications", "workspace", "workspaces",
            "vaccination", "vaccinations", "triage", "clinical", "clinician",
            "clinicians", "patient", "patients", "appointment", "appointments",
            "prescription", "prescriptions", "diagnosis", "medication",
            "medications", "referral", "referrals", "pathology", "radiology",
            "safeguarding", "electronic", "interoperability", "integration",
            "authentication", "configuration", "administration", "demographic",
            "musculoskeletal", "cardiovascular", "respiratory", "dermatology",
        },
    },
    "patients": {
        "label": "Patients / General Public",
        "max_grade": 8, "ideal_grade": 6,
        "max_fog": 10, "ideal_fog": 8,
        "max_aws": 20, "ideal_aws": 15,
        "domain_words": set(),
    },
    "default": {
        "label": "General Audience",
        "max_grade": 12, "ideal_grade": 8,
        "max_fog": 14, "ideal_fog": 10,
        "max_aws": 25, "ideal_aws": 18,
        "domain_words": set(),
    },
}


def get_profile(audience_str: str) -> dict:
    if not audience_str:
        return AUDIENCE_PROFILES["default"]
    key = audience_str.lower().strip()
    for k, v in AUDIENCE_PROFILES.items():
        if k in key or key in k:
            return v
    return AUDIENCE_PROFILES["default"]


# ── Text analysis ─────────────────────────────────────────────

def count_syllables(word: str) -> int:
    word = word.lower()
    if len(word) <= 3:
        return 1
    count = len(re.findall(r"[aeiouy]+", word))
    if word.endswith("e"):
        count -= 1
    if word.endswith("le") and len(word) > 2 and word[-3] not in "aeiouy":
        count += 1
    return max(count, 1)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                meta = {}
            body = parts[2].strip()
            return meta, body
    return {}, text


def strip_markdown(text: str) -> str:
    """Remove markdown syntax to get plain text."""
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)  # images
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # links
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)  # headings
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)  # bold
    text = re.sub(r"\*([^*]+)\*", r"\1", text)  # italic
    text = re.sub(r"^[-*+]\s+", "", text, flags=re.MULTILINE)  # list markers
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)  # blockquotes
    text = re.sub(r"`[^`]+`", "", text)  # inline code
    text = re.sub(r"---+", "", text)  # hr
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def analyse_text(text: str, profile: dict) -> dict:
    """Run full readability analysis on plain text."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 5]
    words = [w for w in re.findall(r"[a-zA-Z']+", text) if len(w) > 1]

    if not words or not sentences:
        return {"empty": True}

    wc = len(words)
    sc = max(len(sentences), 1)
    syls = sum(count_syllables(w) for w in words)
    complex_words = [w for w in words if count_syllables(w) >= 3]
    cplx = len(complex_words)

    aws = wc / sc
    asp = syls / max(wc, 1)

    # Core scores
    flesch = 206.835 - 1.015 * aws - 84.6 * asp
    fk = 0.39 * aws + 11.8 * asp - 15.59
    fog = 0.4 * (aws + 100 * cplx / max(wc, 1))

    chars = sum(len(w) for w in words)
    L = chars / wc * 100
    S = sc / wc * 100
    coleman = 0.0588 * L - 0.296 * S - 15.8

    if sc >= 3:
        smog = 1.043 * math.sqrt(cplx * 30 / sc) + 3.1291
    else:
        smog = fk  # fallback

    # Domain-adjusted
    domain_words = profile.get("domain_words", set())
    domain_cplx = sum(1 for w in complex_words if w.lower() not in domain_words)
    adj_fog = 0.4 * (aws + 100 * domain_cplx / max(wc, 1))

    # Passive voice
    passive = len(re.findall(r"\b(?:is|are|was|were|be|been|being)\s+\w+ed\b", text, re.I))

    # Long sentences
    sent_lengths = [(len(re.findall(r"[a-zA-Z']+", s)), s[:150]) for s in sentences]
    sent_lengths.sort(reverse=True)
    long_sentences = [s for wc_s, s in sent_lengths if wc_s > profile.get("max_aws", 25)]

    # Images check (from original markdown, not stripped)
    # We'll handle this separately

    # Heading structure
    # Also handled separately from markdown source

    return {
        "empty": False,
        "word_count": wc,
        "sentence_count": sc,
        "avg_words_per_sentence": round(aws, 1),
        "avg_syllables_per_word": round(asp, 2),
        "complex_word_count": cplx,
        "complex_word_pct": round(100 * cplx / wc, 1),
        "domain_complex_count": domain_cplx,
        "domain_complex_pct": round(100 * domain_cplx / wc, 1),
        "flesch": round(flesch, 1),
        "fk_grade": round(fk, 1),
        "fog": round(fog, 1),
        "adj_fog": round(adj_fog, 1),
        "coleman": round(coleman, 1),
        "smog": round(smog, 1),
        "passive_count": passive,
        "long_sentence_count": len(long_sentences),
        "longest_sentences": sent_lengths[:3],
    }


def analyse_markdown_structure(md_text: str) -> dict:
    """Analyse markdown-specific accessibility features."""
    images = re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", md_text)
    images_total = len(images)
    images_no_alt = sum(1 for alt, _ in images if not alt.strip())

    headings = re.findall(r"^(#{1,6})\s+(.+)", md_text, re.MULTILINE)
    heading_levels = [len(h[0]) for h in headings]

    # Check heading hierarchy (no skipping levels)
    hierarchy_issues = []
    for i in range(1, len(heading_levels)):
        if heading_levels[i] > heading_levels[i - 1] + 1:
            hierarchy_issues.append(
                f"Jump from h{heading_levels[i-1]} to h{heading_levels[i]} "
                f"(after \"{headings[i-1][1][:40]}\")"
            )

    links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", md_text)
    links_total = len(links)
    vague_link_texts = [t for t, _ in links if t.lower().strip() in
                        ("click here", "here", "link", "this", "read more", "more")]

    return {
        "images_total": images_total,
        "images_no_alt": images_no_alt,
        "headings_total": len(headings),
        "heading_levels": heading_levels,
        "hierarchy_issues": hierarchy_issues,
        "links_total": links_total,
        "vague_links": vague_link_texts,
    }


def generate_recommendations(stats: dict, structure: dict, profile: dict) -> list[dict]:
    """Generate prioritised recommendations based on analysis."""
    recs = []

    if stats.get("empty"):
        recs.append({"severity": "high", "category": "Content",
                      "issue": "Document has no readable content",
                      "fix": "Add meaningful text content to this article."})
        return recs

    p = profile
    label = p["label"]

    # Sentence length
    aws = stats["avg_words_per_sentence"]
    if aws > p["max_aws"]:
        recs.append({"severity": "high", "category": "Readability",
            "issue": f"Average sentence length is {aws} words (max {p['max_aws']} for {label})",
            "fix": f"Break long sentences to target ≤{p['ideal_aws']} words on average."})
    elif aws > p["ideal_aws"]:
        recs.append({"severity": "medium", "category": "Readability",
            "issue": f"Average sentence length is {aws} words (ideal ≤{p['ideal_aws']} for {label})",
            "fix": "Consider splitting the longest sentences for easier scanning."})

    # Grade level
    fk = stats["fk_grade"]
    if fk > p["max_grade"]:
        recs.append({"severity": "high", "category": "Readability",
            "issue": f"Grade level {fk} exceeds max {p['max_grade']} for {label}",
            "fix": "Simplify vocabulary and shorten sentences to reduce grade level."})
    elif fk > p["ideal_grade"]:
        recs.append({"severity": "low", "category": "Readability",
            "issue": f"Grade level {fk} is above ideal {p['ideal_grade']} for {label}",
            "fix": "Minor simplification would improve accessibility."})

    # Fog index
    adj = stats["adj_fog"]
    if adj > p["max_fog"]:
        recs.append({"severity": "high", "category": "Readability",
            "issue": f"Adjusted Fog Index {adj} exceeds max {p['max_fog']}",
            "fix": "Reduce complex (non-domain) words and sentence length."})

    # Long sentences
    if stats["long_sentence_count"] > 0:
        recs.append({"severity": "medium", "category": "Readability",
            "issue": f"{stats['long_sentence_count']} sentence(s) exceed {p['max_aws']} words",
            "fix": "Split these sentences into shorter, clearer statements."})

    # Passive voice
    if stats["passive_count"] > 5:
        recs.append({"severity": "medium", "category": "Clarity",
            "issue": f"{stats['passive_count']} passive voice constructions detected",
            "fix": "Convert passive sentences to active voice for directness."})

    # Images without alt text
    if structure["images_no_alt"] > 0:
        recs.append({"severity": "high", "category": "Accessibility",
            "issue": f"{structure['images_no_alt']} of {structure['images_total']} images have no alt text",
            "fix": "Add descriptive alt text to all images for screen reader users."})

    # Heading hierarchy
    if structure["hierarchy_issues"]:
        for h in structure["hierarchy_issues"][:3]:
            recs.append({"severity": "medium", "category": "Accessibility",
                "issue": f"Heading hierarchy skip: {h}",
                "fix": "Use sequential heading levels (h1→h2→h3) without skipping."})

    # Vague link text
    if structure["vague_links"]:
        recs.append({"severity": "medium", "category": "Accessibility",
            "issue": f"{len(structure['vague_links'])} link(s) with vague text (e.g. \"{structure['vague_links'][0]}\")",
            "fix": "Use descriptive link text that makes sense out of context."})

    # No headings
    if structure["headings_total"] == 0:
        recs.append({"severity": "medium", "category": "Structure",
            "issue": "No headings found in document",
            "fix": "Add section headings to improve scannability and navigation."})

    # Very short content
    if stats["word_count"] < 50:
        recs.append({"severity": "low", "category": "Content",
            "issue": f"Very short article ({stats['word_count']} words)",
            "fix": "Consider whether this article provides enough detail for users."})

    return recs


# ── Persona-based reviews ─────────────────────────────────────

def load_personas(path: str | Path) -> list[dict]:
    """Load reviewer personas from a JSON file."""
    p = Path(path)
    if not p.exists():
        print(f"  Warning: personas file {p} not found, skipping persona reviews")
        return []
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("personas", [])


def persona_review(persona: dict, stats: dict, structure: dict, body: str) -> list[dict]:
    """Run a single persona's checks against a document, returning findings."""
    findings = []
    if stats.get("empty"):
        findings.append({"check": "content", "status": "fail",
                         "note": "Document has no readable content."})
        return findings

    p_read = persona.get("readability", {})
    checks = persona.get("checks", {})

    # Readability checks against this persona's thresholds
    fk = stats["fk_grade"]
    max_g = p_read.get("max_grade", 14)
    ideal_g = p_read.get("ideal_grade", 10)
    if fk > max_g:
        findings.append({"check": "grade_level", "status": "fail",
            "note": f"Grade level {fk} exceeds max {max_g} for this reader."})
    elif fk > ideal_g:
        findings.append({"check": "grade_level", "status": "warn",
            "note": f"Grade level {fk} is above ideal {ideal_g}."})
    else:
        findings.append({"check": "grade_level", "status": "pass",
            "note": f"Grade level {fk} is appropriate."})

    aws = stats["avg_words_per_sentence"]
    max_aws = p_read.get("max_words_per_sentence", 25)
    ideal_aws = p_read.get("ideal_words_per_sentence", 18)
    if aws > max_aws:
        findings.append({"check": "sentence_length", "status": "fail",
            "note": f"Avg {aws} words/sentence exceeds max {max_aws}."})
    elif aws > ideal_aws:
        findings.append({"check": "sentence_length", "status": "warn",
            "note": f"Avg {aws} words/sentence is above ideal {ideal_aws}."})
    else:
        findings.append({"check": "sentence_length", "status": "pass",
            "note": f"Avg {aws} words/sentence is good."})

    # Passive voice
    if stats["passive_count"] > 5:
        findings.append({"check": "passive_voice", "status": "warn",
            "note": f"{stats['passive_count']} passive constructions detected."})
    else:
        findings.append({"check": "passive_voice", "status": "pass",
            "note": f"Low passive voice usage ({stats['passive_count']})."})

    body_lower = body.lower()

    # Run persona-specific checks by heuristic
    for check_id, check_question in checks.items():
        status, note = _run_heuristic_check(check_id, check_question, body, body_lower, stats, structure)
        findings.append({"check": check_id, "status": status, "note": note})

    return findings


def _run_heuristic_check(check_id, question, body, body_lower, stats, structure):
    """Run a heuristic check and return (status, note)."""

    if check_id in ("has_quick_summary",):
        if re.search(r"^#{1,3}\s*(overview|summary|introduction|about)", body, re.I | re.M):
            return "pass", "Document has a summary/overview section."
        return "warn", "No clear summary or overview section at the top."

    if check_id in ("has_step_by_step",):
        if re.search(r"^\d+[\.\)]\s", body, re.M):
            return "pass", "Numbered step-by-step instructions found."
        if re.search(r"^[-*]\s", body, re.M):
            return "warn", "Bullet lists found, but no numbered steps."
        return "warn", "No step-by-step instructions detected."

    if check_id in ("has_screenshots",):
        n = structure.get("images_total", 0)
        if n >= 2: return "pass", f"{n} images/screenshots present."
        if n == 1: return "warn", "Only 1 image — consider adding more."
        return "warn", "No screenshots found."

    if check_id in ("jargon_level", "avoids_jargon"):
        pct = stats.get("domain_complex_pct", 0)
        if pct <= 5: return "pass", f"Low non-domain jargon ({pct}%)."
        if pct <= 10: return "warn", f"Moderate jargon ({pct}% non-domain complex words)."
        return "fail", f"High jargon ({pct}% non-domain complex words)."

    if check_id in ("scannable",):
        h = structure.get("headings_total", 0)
        wc = stats.get("word_count", 0)
        if wc > 200 and h < 2: return "warn", f"Only {h} heading(s) for {wc} words."
        return "pass", f"{h} headings for {wc} words — good scannability."

    if check_id in ("is_concise",):
        aws = stats["avg_words_per_sentence"]
        if aws <= 20: return "pass", "Writing is concise."
        if aws <= 28: return "warn", f"Avg sentence length ({aws}) could be tighter."
        return "fail", f"Avg sentence length ({aws}) — needs trimming."

    if check_id in ("has_clear_outcomes",):
        n = len(re.findall(r"\b(will|should|this means|as a result|you'll see)\b", body_lower))
        if n >= 3: return "pass", "Outcome language found throughout."
        return "warn", "Add clearer outcome statements to sections."

    if check_id in ("mobile_readable",):
        long = sum(1 for l in body.split("\n") if len(l) > 120)
        if long > 5: return "warn", f"{long} long lines may cause scrolling on mobile."
        return "pass", "Content appears mobile-friendly."

    if check_id in ("has_warnings",):
        if re.search(r"(⚠|warning|important|caution|note:)", body_lower):
            return "pass", "Warnings or important notes are highlighted."
        return "info", "No explicit warnings — check if any are needed."

    if check_id in ("time_efficient",):
        wc = stats.get("word_count", 0)
        if wc <= 400: return "pass", f"Short article ({wc} words) — quick to complete."
        if wc <= 800: return "warn", f"Medium article ({wc} words) — may take 2-4 minutes."
        return "warn", f"Long article ({wc} words) — consider splitting."

    if check_id in ("covers_prerequisites", "has_prerequisites"):
        if re.search(r"(prerequisit|before you|you.ll need|require|make sure)", body_lower):
            return "pass", "Prerequisites are mentioned."
        return "warn", "No prerequisites section found."

    if check_id in ("has_ig_considerations",):
        if re.search(r"(governance|security|privacy|data protection|gdpr|ig\b)", body_lower):
            return "pass", "IG considerations mentioned."
        return "info", "No IG/security considerations found."

    if check_id in ("has_role_clarity",):
        if re.search(r"(admin|administrator|user|it team|manager|clinician)", body_lower):
            return "pass", "Role references found."
        return "warn", "Unclear who should perform these actions."

    if check_id in ("version_context", "is_version_specific"):
        if re.search(r"(version|v\d|update|new feature|recently)", body_lower):
            return "pass", "Version or recency context provided."
        return "info", "No version-specific context."

    if check_id in ("has_troubleshooting", "has_error_guidance"):
        if re.search(r"(troubleshoot|error|issue|problem|fix|resolv|can.t|won.t|fail)", body_lower):
            return "pass", "Troubleshooting guidance included."
        return "info", "No troubleshooting section found."

    if check_id in ("has_technical_detail",):
        if re.search(r"`[^`]+`", body) or re.search(r"```", body):
            return "pass", "Technical detail / code references found."
        return "warn", "No technical parameters or config detail found."

    if check_id in ("has_examples",):
        if re.search(r"(example|e\.g\.|for instance|such as|```)", body_lower):
            return "pass", "Examples present."
        return "warn", "No examples found — consider adding some."

    if check_id in ("uses_active_voice",):
        pc = stats.get("passive_count", 0)
        if pc <= 2: return "pass", f"Mostly active voice ({pc} passive)."
        if pc <= 5: return "warn", f"{pc} passive constructions — convert some."
        return "fail", f"{pc} passive constructions — rewrite in active voice."

    if check_id in ("addresses_user_directly",):
        n = len(re.findall(r"\byou\b", body_lower))
        if n >= 3: return "pass", f"Addresses the user directly ({n}× 'you')."
        return "warn", "Doesn't directly address the reader — use 'you'."

    if check_id in ("consistent_terminology",):
        pairs = [("click","tap"),("select","choose"),("press","click"),("workspace","organisation")]
        mixed = [f"'{a}'/'{b}'" for a,b in pairs if a in body_lower and b in body_lower]
        if mixed: return "warn", f"Mixed terminology: {', '.join(mixed[:3])}."
        return "pass", "Terminology appears consistent."

    if check_id in ("has_clear_cta",):
        if re.search(r"(next step|you can now|go to|navigate to|click|select)", body_lower):
            return "pass", "Clear calls to action found."
        return "warn", "No clear next-action prompts found."

    if check_id in ("positive_framing",):
        neg = len(re.findall(r"\b(don.t|do not|never|avoid|cannot|can.t)\b", body_lower))
        pos = len(re.findall(r"\b(you can|to do this|simply|just)\b", body_lower))
        if neg > pos and neg > 3: return "warn", f"More negative ({neg}) than positive ({pos}) framing."
        return "pass", "Positive framing used."

    if check_id in ("images_have_alt",):
        no_alt = structure.get("images_no_alt", 0)
        total = structure.get("images_total", 0)
        if total == 0: return "pass", "No images to check."
        if no_alt == 0: return "pass", f"All {total} images have alt text."
        return "fail", f"{no_alt}/{total} images missing alt text."

    if check_id in ("heading_hierarchy",):
        issues = structure.get("hierarchy_issues", [])
        if not issues: return "pass", "Heading hierarchy is correct."
        return "fail", f"{len(issues)} hierarchy issue(s): {issues[0]}"

    if check_id in ("links_are_descriptive",):
        vague = structure.get("vague_links", [])
        if not vague: return "pass", "All links have descriptive text."
        return "fail", f"{len(vague)} link(s) with vague text ('{vague[0]}')."

    if check_id in ("has_consistent_formatting",):
        mixed = bool(re.search(r"^[-*]\s", body, re.M)) and bool(re.search(r"^\d+\.\s", body, re.M))
        if mixed: return "warn", "Mixed bullet and numbered lists."
        return "pass", "Formatting appears consistent."

    if check_id in ("is_screen_reader_friendly",):
        issues = structure.get("images_no_alt", 0) + len(structure.get("hierarchy_issues", []))
        if issues == 0: return "pass", "Should work well with screen readers."
        return "warn", f"{issues} potential screen reader issue(s)."

    if check_id in ("no_orphan_content",):
        lines = body.strip().split("\n")
        for i, line in enumerate(lines):
            if re.match(r"^#{1,6}\s", line):
                if i > 5: return "warn", f"{i} lines before first heading may be orphaned."
                break
        return "pass", "All content is under headings."

    if check_id in ("has_architecture_context",):
        if re.search(r"(system|architecture|component|service|infra|platform|stack)", body_lower):
            return "pass", "System/architecture context referenced."
        return "warn", "No system-level context — explain where this fits."

    if check_id in ("has_data_flow",):
        if re.search(r"(data flow|integration|sync|sends? to|receives? from|connects? to|API|webhook)", body_lower):
            return "pass", "Data flow or integration points described."
        return "warn", "No data flow or integration description found."

    if check_id in ("has_scalability_notes",):
        if re.search(r"(scal|limit|maximum|capacity|throttl|rate limit|concurrent|performance)", body_lower):
            return "pass", "Scale or capacity considerations mentioned."
        return "info", "No scalability notes — may not be relevant."

    if check_id in ("is_reassuring",):
        reassuring = len(re.findall(r"\b(don.t worry|it.s (ok|okay|normal)|safely|securely|we.ll|help)\b", body_lower))
        if reassuring >= 2:
            return "pass", "Reassuring, supportive tone used."
        if reassuring == 1:
            return "warn", "Limited reassurance — consider adding supportive language."
        return "warn", "No reassuring language found — may feel clinical to patients."

    if check_id in ("has_help_contact",):
        if re.search(r"(contact|support|help|call|phone|email us|get in touch|question)", body_lower):
            return "pass", "Help/contact information provided."
        return "warn", "No help contact or support guidance found."

    if check_id in ("has_batch_guidance",):
        if re.search(r"(batch|bulk|multiple|csv|list|import|export|all at once)", body_lower):
            return "pass", "Batch/bulk operation guidance found."
        return "info", "No batch guidance — may not be relevant for this article."

    return "info", f"'{check_id}' not automated — manual review needed."


# ── Scoring ───────────────────────────────────────────────────

def compute_score(stats: dict, structure: dict, profile: dict) -> int:
    """Compute a 0-100 overall score."""
    if stats.get("empty"):
        return 0

    score = 100
    p = profile

    # Readability penalties
    fk = stats["fk_grade"]
    if fk > p["max_grade"]:
        score -= min(30, (fk - p["max_grade"]) * 5)
    elif fk > p["ideal_grade"]:
        score -= min(10, (fk - p["ideal_grade"]) * 2)

    aws = stats["avg_words_per_sentence"]
    if aws > p["max_aws"]:
        score -= min(20, (aws - p["max_aws"]) * 2)
    elif aws > p["ideal_aws"]:
        score -= min(10, (aws - p["ideal_aws"]))

    # Accessibility penalties
    if structure["images_total"] > 0:
        alt_pct = structure["images_no_alt"] / structure["images_total"]
        score -= int(alt_pct * 20)

    if structure["hierarchy_issues"]:
        score -= min(10, len(structure["hierarchy_issues"]) * 3)

    if structure["vague_links"]:
        score -= min(10, len(structure["vague_links"]) * 2)

    # Passive voice
    if stats["passive_count"] > 5:
        score -= min(10, (stats["passive_count"] - 5) * 2)

    return max(0, min(100, score))


def score_badge(score: int) -> str:
    if score >= 85:
        return "good"
    elif score >= 65:
        return "ok"
    elif score >= 45:
        return "warn"
    else:
        return "bad"


# ── HTML report generation ────────────────────────────────────

REPORT_CSS = """
:root { --accent: #0b8888; --accent-light: #e9faf7; --good: #22c55e;
    --ok: #eab308; --warn: #f97316; --bad: #ef4444; --text: #1a1a1a;
    --text-sec: #555; --border: #e0e0e0; --bg: #fafafa; }
* { box-sizing: border-box; }
body { font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    color: var(--text); background: var(--bg); margin: 0; line-height: 1.6; font-size: 15px; }
header { background: var(--accent); color: white; padding: 2rem; text-align: center; }
header h1 { margin: 0; font-size: 1.8rem; }
header p { margin: 0.3rem 0 0; opacity: 0.85; font-size: 0.95rem; }
.summary { max-width: 1000px; margin: 2rem auto; padding: 0 1.5rem; }
.summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin: 1.5rem 0; }
.stat-card { background: white; border-radius: 10px; padding: 1.25rem;
    border: 1px solid var(--border); text-align: center; }
.stat-card .number { font-size: 2rem; font-weight: 700; color: var(--accent); }
.stat-card .label { font-size: 0.85rem; color: var(--text-sec); margin-top: 0.25rem; }
.filter-bar { margin: 1.5rem 0; display: flex; gap: 0.5rem; flex-wrap: wrap; }
.filter-btn { padding: 0.4rem 0.9rem; border-radius: 20px; border: 1px solid var(--border);
    background: white; cursor: pointer; font-size: 0.85rem; transition: all 0.15s; }
.filter-btn:hover, .filter-btn.active { background: var(--accent); color: white; border-color: var(--accent); }
table { width: 100%; border-collapse: collapse; background: white; border-radius: 10px;
    overflow: hidden; border: 1px solid var(--border); margin: 1rem 0; }
th { background: #f8f8f8; padding: 0.7rem 0.75rem; text-align: left; font-size: 0.8rem;
    text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-sec);
    border-bottom: 2px solid var(--border); position: sticky; top: 0; cursor: pointer; }
th:hover { background: #f0f0f0; }
td { padding: 0.6rem 0.75rem; border-bottom: 1px solid #f0f0f0; font-size: 0.9rem; }
tr:hover { background: var(--accent-light); }
.badge { display: inline-block; padding: 0.15rem 0.6rem; border-radius: 10px;
    font-size: 0.75rem; font-weight: 600; text-transform: uppercase; }
.badge-good { background: #dcfce7; color: #166534; }
.badge-ok { background: #fef9c3; color: #854d0e; }
.badge-warn { background: #ffedd5; color: #9a3412; }
.badge-bad { background: #fecaca; color: #991b1b; }
.score-num { font-weight: 700; font-size: 1.1rem; }
.detail-panel { display: none; background: #fafafa; }
.detail-panel td { padding: 1rem 1.5rem; }
.detail-content { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }
.detail-scores dt { font-weight: 600; font-size: 0.85rem; color: var(--text-sec); }
.detail-scores dd { margin: 0 0 0.75rem 0; font-size: 1rem; }
.rec-list { list-style: none; padding: 0; margin: 0; }
.rec-list li { padding: 0.5rem 0; border-bottom: 1px solid #eee; }
.rec-list li:last-child { border-bottom: none; }
.rec-sev { display: inline-block; width: 6px; height: 6px; border-radius: 50%;
    margin-right: 0.5rem; vertical-align: middle; }
.rec-sev-high { background: var(--bad); }
.rec-sev-medium { background: var(--warn); }
.rec-sev-low { background: var(--ok); }
.rec-category { font-size: 0.75rem; color: var(--text-sec); text-transform: uppercase;
    margin-right: 0.5rem; }
.rec-fix { font-size: 0.85rem; color: var(--text-sec); margin-top: 0.2rem; }
.collection-header { margin: 2rem 0 0.5rem; padding: 0.5rem 0; border-bottom: 2px solid var(--accent);
    font-size: 1.1rem; font-weight: 600; color: var(--accent); }

/* Persona tabs */
.persona-tabs { display: flex; gap: 0; border-bottom: 2px solid var(--border); margin: 1rem 0 0; }
.persona-tab { padding: 0.5rem 1rem; cursor: pointer; font-size: 0.85rem; border: none;
    background: none; color: var(--text-sec); border-bottom: 2px solid transparent;
    margin-bottom: -2px; transition: all 0.15s; }
.persona-tab:hover { color: var(--accent); }
.persona-tab.active { color: var(--accent); border-bottom-color: var(--accent); font-weight: 600; }
.persona-panel { display: none; padding: 1rem 0; }
.persona-panel.active { display: block; }
.persona-header { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.75rem; }
.persona-header .icon { font-size: 1.3rem; }
.persona-header .name { font-weight: 600; }
.persona-header .role { color: var(--text-sec); font-size: 0.85rem; }
.persona-perspective { font-size: 0.85rem; color: var(--text-sec); font-style: italic;
    margin-bottom: 1rem; padding: 0.5rem 0.75rem; background: white; border-radius: 6px;
    border-left: 3px solid var(--accent); }
.check-grid { display: grid; gap: 0.4rem; }
.check-row { display: flex; align-items: start; gap: 0.5rem; font-size: 0.88rem; padding: 0.3rem 0; }
.check-icon { flex-shrink: 0; width: 1.2rem; text-align: center; }
.check-pass .check-icon { color: var(--good); }
.check-warn .check-icon { color: var(--warn); }
.check-fail .check-icon { color: var(--bad); }
.check-info .check-icon { color: #60a5fa; }
@media (max-width: 768px) {
    .detail-content { grid-template-columns: 1fr; }
    .summary-grid { grid-template-columns: 1fr 1fr; }
}
"""

REPORT_JS = """
document.addEventListener('DOMContentLoaded', () => {
    // Toggle detail panels
    document.querySelectorAll('.article-row').forEach(row => {
        row.style.cursor = 'pointer';
        row.addEventListener('click', () => {
            const detail = row.nextElementSibling;
            detail.style.display = detail.style.display === 'table-row' ? 'none' : 'table-row';
        });
    });

    // Filter buttons
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const filter = btn.dataset.filter;
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            document.querySelectorAll('.article-row').forEach(row => {
                const badge = row.dataset.badge;
                const show = filter === 'all' || badge === filter;
                row.style.display = show ? '' : 'none';
                row.nextElementSibling.style.display = 'none';
            });
        });
    });

    // Sort table
    const table = document.getElementById('results-table');
    const tbody = table.querySelector('tbody');
    const headers = table.querySelectorAll('th[data-sort]');

    headers.forEach((th, idx) => {
        th.addEventListener('click', () => {
            const rows = Array.from(tbody.querySelectorAll('.article-row'));
            const key = th.dataset.sort;
            const asc = th.dataset.dir !== 'asc';
            th.dataset.dir = asc ? 'asc' : 'desc';

            rows.sort((a, b) => {
                let va = a.dataset[key] || '';
                let vb = b.dataset[key] || '';
                if (!isNaN(va) && !isNaN(vb)) { va = parseFloat(va); vb = parseFloat(vb); }
                if (va < vb) return asc ? -1 : 1;
                if (va > vb) return asc ? 1 : -1;
                return 0;
            });

            rows.forEach(row => {
                tbody.appendChild(row);
                tbody.appendChild(row.nextElementSibling);
            });
        });
    });

    // Persona tabs
    document.querySelectorAll('.persona-tab').forEach(tab => {
        tab.addEventListener('click', (e) => {
            e.stopPropagation();
            const container = tab.closest('.persona-reviews');
            container.querySelectorAll('.persona-tab').forEach(t => t.classList.remove('active'));
            container.querySelectorAll('.persona-panel').forEach(p => p.classList.remove('active'));
            tab.classList.add('active');
            container.querySelector('#' + tab.dataset.panel).classList.add('active');
        });
    });
});
"""


def generate_report(results: list[dict], output_path: Path):
    """Generate the full HTML report."""
    total = len(results)
    scored = [r for r in results if not r["stats"].get("empty")]
    avg_score = sum(r["score"] for r in scored) / max(len(scored), 1)
    avg_grade = sum(r["stats"]["fk_grade"] for r in scored) / max(len(scored), 1)
    avg_aws = sum(r["stats"]["avg_words_per_sentence"] for r in scored) / max(len(scored), 1)
    total_recs = sum(len(r["recommendations"]) for r in results)
    high_recs = sum(1 for r in results for rec in r["recommendations"] if rec["severity"] == "high")

    badge_counts = Counter(r["badge"] for r in results)

    # Group by collection
    by_collection = {}
    for r in results:
        col = r["meta"].get("collection", "Uncategorised")
        by_collection.setdefault(col, []).append(r)

    # Build table rows
    table_rows = []
    for col_name, col_results in sorted(by_collection.items()):
        for r in sorted(col_results, key=lambda x: x["score"]):
            s = r["stats"]
            m = r["meta"]
            recs = r["recommendations"]

            # Main row
            rec_summary = ""
            if recs:
                high = sum(1 for x in recs if x["severity"] == "high")
                med = sum(1 for x in recs if x["severity"] == "medium")
                low = sum(1 for x in recs if x["severity"] == "low")
                parts = []
                if high: parts.append(f'<span style="color:var(--bad)">{high} high</span>')
                if med: parts.append(f'<span style="color:var(--warn)">{med} med</span>')
                if low: parts.append(f'<span style="color:var(--ok)">{low} low</span>')
                rec_summary = ", ".join(parts)
            else:
                rec_summary = '<span style="color:var(--good)">None</span>'

            empty = s.get("empty", False)
            row = f"""<tr class="article-row" data-badge="{r['badge']}"
                data-score="{r['score']}" data-grade="{s.get('fk_grade', 0)}"
                data-aws="{s.get('avg_words_per_sentence', 0)}" data-title="{m.get('title', '')}">
                <td><strong>{m.get('title', 'Untitled')[:60]}</strong>
                    <br><small style="color:var(--text-sec)">{col_name}</small></td>
                <td class="score-num">{r['score']}</td>
                <td><span class="badge badge-{r['badge']}">{r['badge']}</span></td>
                <td>{s.get('fk_grade', '-') if not empty else '-'}</td>
                <td>{s.get('avg_words_per_sentence', '-') if not empty else '-'}</td>
                <td>{s.get('word_count', '-') if not empty else '-'}</td>
                <td>{rec_summary}</td>
            </tr>"""

            # Detail panel
            if not empty:
                rec_items = ""
                for rec in recs:
                    rec_items += f"""<li>
                        <span class="rec-sev rec-sev-{rec['severity']}"></span>
                        <span class="rec-category">{rec['category']}</span>
                        {rec['issue']}
                        <div class="rec-fix">💡 {rec['fix']}</div>
                    </li>"""

                # Persona review tabs
                persona_reviews = r.get("persona_reviews", {})
                persona_html = ""
                if persona_reviews:
                    uid = r['file'].replace('.', '_')
                    tabs = ""
                    panels = ""
                    first = True
                    for pid, prev in persona_reviews.items():
                        p = prev["persona"]
                        findings = prev["findings"]
                        active = "active" if first else ""
                        panel_id = f"p_{uid}_{pid}"
                        tabs += f'<button class="persona-tab {active}" data-panel="{panel_id}">{p["icon"]} {p["name"].split()[0]}</button>'

                        status_icons = {"pass": "✅", "warn": "⚠️", "fail": "❌", "info": "ℹ️"}
                        check_rows = ""
                        pass_count = sum(1 for f_ in findings if f_["status"] == "pass")
                        warn_count = sum(1 for f_ in findings if f_["status"] == "warn")
                        fail_count = sum(1 for f_ in findings if f_["status"] == "fail")

                        for f_ in findings:
                            icon = status_icons.get(f_["status"], "•")
                            check_rows += f'<div class="check-row check-{f_["status"]}"><span class="check-icon">{icon}</span><span>{f_["note"]}</span></div>'

                        summary_line = f'<span style="color:var(--good)">{pass_count}✓</span>'
                        if warn_count: summary_line += f' <span style="color:var(--warn)">{warn_count}⚠</span>'
                        if fail_count: summary_line += f' <span style="color:var(--bad)">{fail_count}✗</span>'

                        panels += f'''<div class="persona-panel {active}" id="{panel_id}">
                            <div class="persona-header">
                                <span class="icon">{p["icon"]}</span>
                                <span class="name">{p["name"]}</span>
                                <span class="role">— {p["role"]}</span>
                                <span style="margin-left:auto;font-size:0.85rem">{summary_line}</span>
                            </div>
                            <div class="persona-perspective">{p["perspective"]}</div>
                            <div class="check-grid">{check_rows}</div>
                        </div>'''
                        first = False

                    persona_html = f'<div class="persona-reviews"><h4>Persona Reviews</h4><div class="persona-tabs">{tabs}</div>{panels}</div>'

                detail = f"""<tr class="detail-panel"><td colspan="7">
                    <div class="detail-content">
                        <div>
                            <h4>Scores</h4>
                            <dl class="detail-scores">
                                <dt>Flesch Reading Ease</dt><dd>{s['flesch']}</dd>
                                <dt>Flesch-Kincaid Grade</dt><dd>{s['fk_grade']}</dd>
                                <dt>Gunning Fog (adjusted)</dt><dd>{s['adj_fog']}</dd>
                                <dt>SMOG Index</dt><dd>{s['smog']}</dd>
                                <dt>Complex words</dt><dd>{s['complex_word_count']} ({s['complex_word_pct']}%)</dd>
                                <dt>Domain-adjusted complex</dt><dd>{s['domain_complex_count']} ({s['domain_complex_pct']}%)</dd>
                                <dt>Passive voice</dt><dd>{s['passive_count']}</dd>
                                <dt>Images without alt</dt><dd>{r['structure']['images_no_alt']}/{r['structure']['images_total']}</dd>
                            </dl>
                        </div>
                        <div>
                            <h4>Recommendations ({len(recs)})</h4>
                            <ul class="rec-list">{rec_items if recs else '<li><em>None — looking good!</em></li>'}</ul>
                        </div>
                    </div>
                    {persona_html}
                </td></tr>"""
            else:
                detail = '<tr class="detail-panel"><td colspan="7"><em>Empty document — no analysis possible.</em></td></tr>'

            table_rows.append(row + detail)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Readability &amp; Accessibility Report</title>
<style>{REPORT_CSS}</style>
</head>
<body>
<header>
    <h1>📊 Readability &amp; Accessibility Report</h1>
    <p>Help Centre &mdash; Generated {date.today()}</p>
</header>
<div class="summary">

    <div class="summary-grid">
        <div class="stat-card">
            <div class="number">{total}</div>
            <div class="label">Articles Analysed</div>
        </div>
        <div class="stat-card">
            <div class="number">{avg_score:.0f}</div>
            <div class="label">Average Score</div>
        </div>
        <div class="stat-card">
            <div class="number">{avg_grade:.1f}</div>
            <div class="label">Avg Grade Level</div>
        </div>
        <div class="stat-card">
            <div class="number">{avg_aws:.0f}</div>
            <div class="label">Avg Words/Sentence</div>
        </div>
        <div class="stat-card">
            <div class="number">{total_recs}</div>
            <div class="label">Total Recommendations</div>
        </div>
        <div class="stat-card">
            <div class="number" style="color:var(--bad)">{high_recs}</div>
            <div class="label">High Priority Issues</div>
        </div>
    </div>

    <div class="filter-bar">
        <button class="filter-btn active" data-filter="all">All ({total})</button>
        <button class="filter-btn" data-filter="good">✅ Good ({badge_counts.get('good', 0)})</button>
        <button class="filter-btn" data-filter="ok">🟡 OK ({badge_counts.get('ok', 0)})</button>
        <button class="filter-btn" data-filter="warn">🟠 Warn ({badge_counts.get('warn', 0)})</button>
        <button class="filter-btn" data-filter="bad">🔴 Bad ({badge_counts.get('bad', 0)})</button>
    </div>

    <table id="results-table">
    <thead>
        <tr>
            <th data-sort="title">Article</th>
            <th data-sort="score">Score</th>
            <th>Rating</th>
            <th data-sort="grade">Grade</th>
            <th data-sort="aws">Words/Sent</th>
            <th>Words</th>
            <th>Issues</th>
        </tr>
    </thead>
    <tbody>
    {"".join(table_rows)}
    </tbody>
    </table>

</div>
<script>{REPORT_JS}</script>
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
    print(f"Report saved: {output_path} ({output_path.stat().st_size:,} bytes)")


# ── Main ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Analyse readability of markdown files")
    parser.add_argument("--input-dir", default="site/markdown",
                        help="Directory containing .md files")
    parser.add_argument("--output", default="site/readability-report.html",
                        help="Output HTML report path")
    parser.add_argument("--personas", default="personas.json",
                        help="Path to reviewer personas JSON file")
    args = parser.parse_args()

    md_dir = Path(args.input_dir)
    if not md_dir.exists():
        print(f"Error: {md_dir} not found")
        sys.exit(1)

    md_files = sorted(md_dir.glob("*.md"))
    print(f"Found {len(md_files)} markdown files in {md_dir}")

    # Load personas
    personas = load_personas(args.personas)
    if personas:
        print(f"Loaded {len(personas)} reviewer personas: {', '.join(p['name'] for p in personas)}")
    else:
        print("No personas loaded — skipping persona reviews")

    results = []
    for i, f in enumerate(md_files):
        raw = f.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(raw)

        audience = meta.get("audience", "")
        profile = get_profile(audience)

        plain = strip_markdown(body)
        stats = analyse_text(plain, profile)
        structure = analyse_markdown_structure(body)
        recs = generate_recommendations(stats, structure, profile)
        score = compute_score(stats, structure, profile)
        badge = score_badge(score)

        # Run persona reviews
        p_reviews = {}
        for persona in personas:
            findings = persona_review(persona, stats, structure, body)
            p_reviews[persona["id"]] = {"persona": persona, "findings": findings}

        results.append({
            "file": f.name,
            "meta": meta,
            "stats": stats,
            "structure": structure,
            "recommendations": recs,
            "score": score,
            "badge": badge,
            "persona_reviews": p_reviews,
        })

        if (i + 1) % 50 == 0:
            print(f"  Analysed {i + 1}/{len(md_files)}...")

    print(f"  Analysed {len(results)} documents")

    # Sort by score ascending (worst first)
    results.sort(key=lambda x: x["score"])

    generate_report(results, Path(args.output))

    # Print summary
    badges = Counter(r["badge"] for r in results)
    print(f"\nSummary:")
    print(f"  Good: {badges.get('good', 0)}")
    print(f"  OK:   {badges.get('ok', 0)}")
    print(f"  Warn: {badges.get('warn', 0)}")
    print(f"  Bad:  {badges.get('bad', 0)}")


if __name__ == "__main__":
    main()
