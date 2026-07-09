from __future__ import annotations


_TOPIC_EXAMPLES = {
    "PTO, vacation, and sick leave": [
        "How far in advance should I request vacation?",
        "Can I request partial-day PTO?",
        "What happens after I submit a leave request?",
    ],
    "Salary and payroll": [
        "How often are salaries paid?",
        "When is payroll processed?",
        "Who should I contact about a payroll issue?",
    ],
    "Employee benefits": [
        "When can I enroll in benefits?",
        "Which plans are available to employees?",
        "What counts as a qualifying life event change?",
    ],
    "Work schedules and shifts": [
        "How are shift changes handled?",
        "Do overtime hours require approval?",
        "How should sick leave be reported?",
    ],
    "IT support (VPN, access permissions, password reset)": [
        "How do I request VPN access?",
        "How do password resets work?",
        "When is access provisioned for new hires?",
    ],
}

_DEFAULT_EXAMPLES = [
    "What is the policy for this topic?",
    "What are the main eligibility rules?",
    "What are the next steps or approvals?",
]


def get_topic_examples(topic: str) -> list[str]:
    return list(_TOPIC_EXAMPLES.get(topic, _DEFAULT_EXAMPLES))
