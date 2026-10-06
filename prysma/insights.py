"""Actionable Insights — Translates findings into plain-English recommendations."""
from typing import Optional
from datetime import datetime

from prysma.storage.database import db
from prysma.security import build_safe_analysis_prompt


class ActionableInsights:
    """Transforms raw findings into strategic recommendations."""

    # Templates for common finding types
    INSIGHT_TEMPLATES = {
        'pricing_change': {
            'emoji': '💰',
            'title': 'Pricing Change Detected',
            'questions': [
                'Are they undercutting you or moving upmarket?',
                'Is this a permanent cut or a launch promotion?',
                'How does their new price compare to yours?'
            ],
            'actions': [
                'Match their price if you have similar value',
                'Differentiate on features they don\'t offer',
                'Double down on premium positioning if they went budget'
            ]
        },
        'product_launch': {
            'emoji': '🚀',
            'title': 'New Product/Feature Launch',
            'questions': [
                'Does this overlap with your product?',
                'What\'s the market reception?',
                'How fast did they ship this?'
            ],
            'actions': [
                'Analyze their launch tweet for market signals',
                'Check if customers are asking for this feature',
                'Consider if you need to respond or stay the course'
            ]
        },
        'hiring': {
            'emoji': '👥',
            'title': 'Hiring Activity',
            'questions': [
                'What roles are they hiring?',
                'Is this expansion or replacement?',
                'Which department is growing?'
            ],
            'actions': [
                'Engineering hires → they\'re building something new',
                'Sales hires → they\'re scaling go-to-market',
                'Marketing hires → they\'re pushing awareness'
            ]
        },
        'funding': {
            'emoji': '💵',
            'title': 'Funding / Financial News',
            'questions': [
                'How much did they raise?',
                'What will they use it for?',
                'How does this change the competitive landscape?'
            ],
            'actions': [
                'Expect them to be more aggressive on pricing',
                'They may increase ad spend → monitor your CAC',
                'Consider if you need to raise as well'
            ]
        },
        'partnership': {
            'emoji': '🤝',
            'title': 'Partnership / Integration',
            'questions': [
                'Who did they partner with?',
                'Does this give them distribution advantage?',
                'Should you seek similar partnerships?'
            ],
            'actions': [
                'Evaluate if you need a competing partnership',
                'Consider if this opens up a new niche for you',
                'Monitor integration quality — partnerships often fail'
            ]
        },
        'negative_news': {
            'emoji': '⚠️',
            'title': 'Negative News / Crisis',
            'questions': [
                'How severe is this?',
                'Is this a product problem or PR problem?',
                'Can you benefit from their trouble?'
            ],
            'actions': [
                'Reach to their dissatisfied customers',
                'Create content addressing the issue they\'re facing',
                'Be careful not to look like you\'re kicking them while down'
            ]
        },
        'content': {
            'emoji': '📝',
            'title': 'Content / SEO Activity',
            'questions': [
                'What topics are they covering?',
                'Is their content driving engagement?',
                'Are they ranking for your target keywords?'
            ],
            'actions': [
                'Create better content on the same topics',
                'Target long-tail keywords they\'re missing',
                'Repurpose your existing content into their formats'
            ]
        }
    }

    def classify_finding(self, finding: dict) -> str:
        """Classify finding into a category.

        Uses the category stored by AnalystAgent.classify_finding (Nano) when
        present. Falls back to keyword matching.
        """
        if finding.get('finding_type') in self.INSIGHT_TEMPLATES:
            return finding['finding_type']

        title = finding['title'].lower()
        content = finding.get('content', '').lower() if finding.get('content') else ''
        combined = f"{title} {content}"

        # Keywords for classification
        if any(w in combined for w in ['price', 'pricing', 'cost', 'plan', 'subscription', '$', '£']):
            return 'pricing_change'
        elif any(w in combined for w in ['launch', 'release', 'announce', 'new feature', 'introducing']):
            return 'product_launch'
        elif any(w in combined for w in ['hiring', 'hire', 'joining', 'team', 'career', 'job']):
            return 'hiring'
        elif any(w in combined for w in ['raise', 'funding', 'series', 'investor', 'million', 'seed']):
            return 'funding'
        elif any(w in combined for w in ['partner', 'integration', 'collaborate', 'team up']):
            return 'partnership'
        elif any(w in combined for w in ['issue', 'problem', 'outage', 'bug', 'complaint', 'angry']):
            return 'negative_news'
        elif any(w in combined for w in ['blog', 'post', 'article', 'content', 'seo', 'guide']):
            return 'content'
        else:
            return 'product_launch'  # Default

    def generate_insight(self, finding: dict) -> str:
        """Generate actionable insight for a single finding."""
        category = self.classify_finding(finding)
        template = self.INSIGHT_TEMPLATES.get(category, self.INSIGHT_TEMPLATES['product_launch'])

        lines = [
            f"{template['emoji']} *{template['title']}*",
            f"",
            f"📌 _{finding['title']}_",
            f"",
            f"🤔 *Key Questions:*"
        ]

        for q in template['questions']:
            lines.append(f"  • {q}")

        lines.append(f"")
        lines.append(f"✅ *Recommended Actions:*")

        for a in template['actions']:
            lines.append(f"  → {a}")

        return '\n'.join(lines)

    def generate_competitor_report(self, competitor_name: str) -> str:
        """Generate full actionable report for a competitor."""
        findings = db.get_recent_findings(hours=168)
        comp_findings = [f for f in findings if f.get('competitor_name', '').lower() == competitor_name.lower()]

        if not comp_findings:
            return f"📊 No recent findings for {competitor_name}. Keep watching!"

        lines = [
            f"📊 *{competitor_name} — Actionable Intelligence*",
            f"_{datetime.now().strftime('%Y-%m-%d %H:%M')}_",
            f"",
            f"📋 *Summary:* {len(comp_findings)} updates in the last 7 days",
            f""
        ]

        # Group by category
        categories = {}
        for f in comp_findings:
            cat = self.classify_finding(f)
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(f)

        # Generate insights per category
        for cat, findings_list in categories.items():
            template = self.INSIGHT_TEMPLATES.get(cat, self.INSIGHT_TEMPLATES['product_launch'])
            lines.append(f"{template['emoji']} *{template['title']}* ({len(findings_list)} items)")

            for f in findings_list[:2]:  # Top 2 per category
                lines.append(f"  • {f['title'][:80]}")

            lines.append(f"")

        # Strategic recommendations
        lines.append(f"🎯 *Strategic Takeaways:*")

        if 'pricing_change' in categories:
            lines.append(f"  💰 They're adjusting pricing — review your pricing page")
        if 'product_launch' in categories:
            lines.append(f"  🚀 They're shipping fast — prioritize your roadmap")
        if 'hiring' in categories:
            lines.append(f"  👥 They're growing — expect more competitive pressure")
        if 'funding' in categories:
            lines.append(f"  💵 They have fuel — prepare for aggressive moves")
        if 'negative_news' in categories:
            lines.append(f"  ⚠️ They're vulnerable — opportunity to capture users")

        return '\n'.join(lines)

    def generate_eli5_summary(self, finding: str) -> str:
        """Generate 'Explain Like I'm 5' summary using AI."""
        prompt = build_safe_analysis_prompt(finding)

        # Add ELI5 instruction
        eli5_prompt = prompt + """

Now explain this like I'm a busy founder who needs to know:
1. What happened (in one sentence)
2. Why it matters (in one sentence)  
3. What I should do about it (one action)

Keep it simple. No jargon. Use emojis."""

        return eli5_prompt

    def generate_weekly_action_plan(self) -> str:
        """Generate a weekly action plan based on all findings."""
        findings = db.get_recent_findings(hours=168)

        if not findings:
            return "📋 No action items this week. Use this time to build!"

        # Categorize all findings
        categories = {}
        for f in findings:
            cat = self.classify_finding(f)
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(f)

        lines = [
            f"📋 *Weekly Action Plan*",
            f"_{datetime.now().strftime('%Y-%m-%d')}_",
            f"",
            f"Based on {len(findings)} competitive signals this week:",
            f""
        ]

        # Priority order
        priority_order = ['pricing_change', 'product_launch', 'negative_news', 'funding', 'hiring', 'partnership', 'content']

        action_num = 1
        for cat in priority_order:
            if cat in categories:
                template = self.INSIGHT_TEMPLATES[cat]
                lines.append(f"{action_num}. {template['emoji']} {template['title']}")
                lines.append(f"   → {template['actions'][0]}")
                lines.append(f"")
                action_num += 1

        lines.append(f"💡 *Pro tip:* Focus on the top 3. Ignore the rest for now.")

        return '\n'.join(lines)
