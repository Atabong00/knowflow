"""
Quiz Generator Service — Section 34

Improves the existing quiz generator.  Since the project does not already
contain an external AI dependency, this module uses a built-in, deterministic
question template bank that is populated from the company's existing knowledge
base.  Generated questions are stored using the application's normal quiz data
model and must be reviewed before publication.
"""
import json
import random
from sqlalchemy.orm import Session

from app.models.training import Assessment, Question
from app.utils import log_audit

# Built-in question template bank seeded from company knowledge (section 34)
QUESTION_TEMPLATES = {
    "Cybersecurity": {
        "multiple_choice": [
            {
                "question": "Which action is the safest when receiving a suspicious email?",
                "options": ["Open the attachment to inspect it", "Reply to the sender for clarification",
                            "Report the email using the company's reporting procedure", "Forward it to colleagues"],
                "answer_index": 2,
                "explanation": "Suspicious emails should be reported through approved channels so the security team can investigate.",
                "topics": ["Phishing Awareness", "Incident Reporting"],
            },
            {
                "question": "Employees should reuse the same password for multiple company systems.",
                "options": ["True", "False"],
                "answer_index": 1,
                "explanation": "Reusing passwords across systems increases the blast radius of a breach.",
                "topics": ["Password Security"],
            },
            {
                "question": "What should you do if you discover a lost company device?",
                "options": ["Ignore it", "Immediately report to IT security", "Try to find the owner yourself", "Leave it where you found it"],
                "answer_index": 1,
                "explanation": "Lost devices must be reported immediately to minimise security risk.",
                "topics": ["Device Security", "Incident Reporting"],
            },
        ],
        "true_false": [
            {
                "question": "Locking your workstation when away from your desk is a recommended security practice.",
                "options": ["True", "False"],
                "answer_index": 0,
                "explanation": "Physical security is as important as digital security.",
                "topics": ["Device Security"],
            },
        ],
        "multiple_select": [
            {
                "question": "Which of the following are signs of a phishing email? (Select all that apply)",
                "options": ["Urgent language demanding immediate action", "Sender address matches the claimed company domain exactly",
                            "Suspicious links or unexpected attachments", "Generic greeting such as 'Dear Customer'"],
                "answer_indices": [0, 2, 3],
                "explanation": "Phishing emails often use urgency, suspicious links, and generic greetings.",
                "topics": ["Phishing Awareness"],
            },
        ],
    },
    "Company Policies": {
        "multiple_choice": [
            {
                "question": "How often must mandatory cybersecurity training be completed?",
                "options": ["Once on hire", "Annually", "Every 5 years", "Only when requested"],
                "answer_index": 1,
                "explanation": "Annual training keeps everyone up to date on evolving threats.",
                "topics": ["Policy Compliance"],
            },
        ],
        "true_false": [
            {
                "question": "Remote work requires explicit manager approval.",
                "options": ["True", "False"],
                "answer_index": 0,
                "explanation": "Check the Remote Work Policy for approval requirements.",
                "topics": ["Policy Compliance"],
            },
        ],
    },
    "Data Protection": {
        "multiple_choice": [
            {
                "question": "Under GDPR, how long should employee personal data be retained after termination?",
                "options": ["Indefinitely", "7 years", "As long as business need exists", "Until the next payroll cycle"],
                "answer_index": 2,
                "explanation": "Data should be retained only as long as there is a documented business need.",
                "topics": ["Compliance"],
            },
        ],
        "true_false": [
            {
                "question": "Personal data must be encrypted both in transit and at rest.",
                "options": ["True", "False"],
                "answer_index": 0,
                "explanation": "Encryption protects data from interception and unauthorised access.",
                "topics": ["Data Protection"],
            },
        ],
    },
    "Compliance": {
        "multiple_choice": [
            {
                "question": "What is the maximum allowed risk level for third-party vendor relationships?",
                "options": ["Low", "Medium", "High", "Unassessed"],
                "answer_index": 1,
                "explanation": "Vendor relationships must not exceed a Medium risk level without additional controls.",
                "topics": ["Vendor Management"],
            },
        ],
    },
}

QUESTION_TYPE_LABELS = {
    "multiple_choice": "Multiple Choice",
    "true_false": "True / False",
    "multiple_select": "Multiple Select",
}


class QuizGenerator:
    """Deterministic quiz generator using a built-in question template bank."""

    @staticmethod
    def generate_questions(
        topic: str,
        num_questions: int,
        difficulty: str,
        question_type: str,
        points: int,
    ) -> list[dict]:
        """Generate a list of question dicts from the template bank."""
        templates = QUESTION_TEMPLATES.get(topic, {})
        questions_out = []

        if question_type and question_type != "any":
            pool = templates.get(question_type, [])
        else:
            pool = []
            for qtype, qlist in templates.items():
                pool.extend(qlist)

        # Shuffle deterministically by using random with a fixed seed based on topic
        rng = random.Random(hash(topic) % 2**31)
        rng.shuffle(pool)

        for i, tmpl in enumerate(pool[:num_questions]):
            qtype = question_type if question_type and question_type != "any" else (
                "true_false" if len(tmpl["options"]) == 2 and
                tmpl["options"][0].lower() == "true" and tmpl["options"][1].lower() == "false"
                else ("multiple_select" if "answer_indices" in tmpl else "multiple_choice")
            )

            if qtype == "multiple_select":
                answer_indices = tmpl.get("answer_indices")
                if not answer_indices:
                    idx = tmpl.get("answer_index")
                    answer_indices = [idx] if idx is not None else []
                correct = json.dumps([tmpl["options"][i] for i in answer_indices])
            elif qtype == "true_false":
                correct = tmpl["options"][tmpl["answer_index"]]
            else:
                correct = tmpl["options"][tmpl["answer_index"]]

            questions_out.append({
                "type": qtype,
                "question_text": tmpl["question"],
                "options": json.dumps(tmpl["options"]),
                "correct_answer": correct,
                "points": points,
                "explanation": tmpl.get("explanation", ""),
                "difficulty": difficulty,
                "topic": ",".join(tmpl.get("topics", [topic])) if isinstance(tmpl.get("topics", [topic]), list) else topic,
                "order": i,
            })

        return questions_out

    @staticmethod
    def create_draft_assessment(
        db: Session,
        course_id: int,
        title: str,
        topic: str,
        num_questions: int,
        difficulty: str,
        question_type: str,
        points: int,
        user_keycloak_id: str,
    ) -> Assessment:
        """Create a draft assessment with generated (unpublished) questions.

        Questions are created in draft state and must be reviewed before publication.
        """
        assessment = Assessment(
            course_id=course_id,
            title=title,
            passing_score=70,
            max_attempts=3,
            retakes_allowed=True,
            published=False,
        )
        db.add(assessment)
        db.commit()
        db.refresh(assessment)

        gen_qs = QuizGenerator.generate_questions(
            topic, num_questions, difficulty, question_type, points
        )
        for gq in gen_qs:
            q = Question(
                assessment_id=assessment.id,
                type=gq["type"],
                question=gq["question_text"],
                options=gq["options"],
                correct_answer=gq["correct_answer"],
                points=gq["points"],
                explanation=gq["explanation"],
                difficulty=gq["difficulty"],
                topic=gq["topic"],
                order=gq["order"],
            )
            db.add(q)

        db.commit()
        db.refresh(assessment)

        log_audit(
            db=db,
            action="GENERATE_QUIZ",
            user_id=user_keycloak_id,
            target_id=assessment.id,
            details=f"Generated {len(gen_qs)} questions for '{title}' (topic={topic}, difficulty={difficulty}, type={question_type}, points={points}) — NOT published",
        )
        return assessment


def seed_training_data(db: Session):
    """Seed sample training data from the company knowledge base.

    Creates published courses with modules, learning material linked to
    existing documents, and assessments with questions.
    """
    from app.models.training import Course, Module, Assessment, Question

    # Check if data already exists
    if db.query(Course).count() > 0:
        return

    # --- Course 1: Information Security Awareness ---
    course1 = Course(
        title="Information Security Awareness",
        slug="information-security-awareness",
        description="Learn the company's security policies, incident procedures, and how to protect company systems from common threats.",
        objectives="Identify phishing attacks\nProtect company credentials\nRecognize social engineering\nReport security incidents",
        category="Cybersecurity",
        difficulty="Beginner",
        duration="45 min",
        published=True,
        mandatory=True,
        passing_score=70,
        start_date=None,
        due_date=None,
        requires_module_completion=True,
    )
    db.add(course1)
    db.commit()

    # Module 1: Password Security
    assess1_1 = Assessment(
        course_id=course1.id,
        title="Password Security Quiz",
        passing_score=70,
        max_attempts=3,
        retakes_allowed=True,
        published=True,
    )
    db.add(assess1_1)
    db.commit()

    module1 = Module(
        course_id=course1.id,
        title="Password Security",
        content="# Password Security\n\nAll employees must follow the company password policy:\n\n1. **Minimum 12 characters** with a mix of upper and lower case, numbers, and special characters.\n2. **Never reuse** passwords from personal or previous accounts.\n3. Use the **company-approved password manager** for storing credentials.\n4. **Change passwords immediately** if you suspect compromise.\n5. Enable **multi-factor authentication (MFA)** on all systems that support it.",
        content_type="markdown",
        order=1,
        assessment_id=assess1_1.id,
    )
    db.add(module1)

    # Module 2: Phishing Awareness
    assess1_2 = Assessment(
        course_id=course1.id,
        title="Phishing Awareness Quiz",
        passing_score=70,
        max_attempts=3,
        retakes_allowed=True,
        published=True,
    )
    db.add(assess1_2)
    db.commit()

    module2 = Module(
        course_id=course1.id,
        title="Phishing Awareness",
        content="# Phishing Awareness\n\nPhishing is a cyber attack method used to trick employees into revealing sensitive information.\n\n**Red flags to watch for:**\n- Urgent language demanding immediate action\n- Suspicious sender email addresses\n- Unexpected attachments or links\n- Generic greetings (e.g., 'Dear Customer')\n\n**What to do:**\n- Do NOT click on links or download attachments from unknown senders\n- Report suspicious emails to the security team using the official reporting procedure\n- Verify requests through a secondary channel if possible\n\n**Reporting procedure:** Forward the email as an attachment to security@company.local with the subject 'PHISHING REPORT'.",
        content_type="markdown",
        order=2,
        assessment_id=assess1_2.id,
    )
    db.add(module2)

    # Module 3: Social Engineering
    assess1_3 = Assessment(
        course_id=course1.id,
        title="Social Engineering Quiz",
        passing_score=70,
        max_attempts=3,
        retakes_allowed=True,
        published=True,
    )
    db.add(assess1_3)
    db.commit()

    module3 = Module(
        course_id=course1.id,
        title="Social Engineering",
        content="# Social Engineering Awareness\n\nSocial engineering exploits human psychology to gain unauthorised access.\n\n**Common techniques:**\n- Pretexting: Creating a fabricated scenario to obtain information\n- Baiting: Offering something in exchange for information or access\n- Tailgating: Following authorised personnel into restricted areas\n\n**Defence strategies:**\n- Always verify identity before sharing information\n- Challenge unknown individuals in secure areas\n- Report suspicious interactions to security immediately",
        content_type="markdown",
        order=3,
        assessment_id=assess1_3.id,
    )
    db.add(module3)

    # Module 4: Device Security
    assess1_4 = Assessment(
        course_id=course1.id,
        title="Device Security Quiz",
        passing_score=70,
        max_attempts=3,
        retakes_allowed=True,
        published=True,
    )
    db.add(assess1_4)
    db.commit()

    module4 = Module(
        course_id=course1.id,
        title="Device Security",
        content="# Device Security\n\nCompany devices must be secured at all times.\n\n**Laptops & Workstations:**\n- Lock screens when stepping away (Win+L / Ctrl+Cmd+Q)\n- Enable full-disk encryption (BitLocker / FileVault)\n- Keep operating system and antivirus updated\n\n**Mobile Devices:**\n- Use PIN or biometric authentication\n- Enable remote wipe capability\n- Do not jailbreak or root devices\n\n**Reporting lost/stolen devices:** Immediately contact IT Security at security@company.local.",
        content_type="markdown",
        order=4,
        assessment_id=assess1_4.id,
    )
    db.add(module4)

    # Module 5: Incident Reporting
    assess1_5 = Assessment(
        course_id=course1.id,
        title="Incident Reporting Quiz",
        passing_score=70,
        max_attempts=3,
        retakes_allowed=True,
        published=True,
    )
    db.add(assess1_5)
    db.commit()

    module5 = Module(
        course_id=course1.id,
        title="Incident Reporting",
        content="# Incident Reporting\n\n**If you discover or suspect a security incident:**\n\n1. **Immediate** — Report within 2 hours to security@company.local\n2. **Do not** attempt to investigate yourself\n3. **Isolate** affected systems if safely possible\n4. **Preserve** evidence (do not power off unless necessary)\n5. **Follow up** with the security team as requested\n\n**What constitutes a reportable incident:**\n- Lost or stolen company devices\n- Suspected phishing or social engineering attempts\n- Unauthorised access attempts\n- Unusual network activity or system behaviour",
        content_type="markdown",
        order=5,
        assessment_id=assess1_5.id,
    )
    db.add(module5)

    # Final Assessment for Course 1
    assess1_final = Assessment(
        course_id=course1.id,
        title="Information Security Final Assessment",
        passing_score=70,
        max_attempts=5,
        retakes_allowed=True,
        published=True,
    )
    db.add(assess1_final)
    db.commit()

    # --- Seed questions for each assessment ---

    # Password Security questions
    questions_ps = [
        ("multiple_choice", "What is the minimum password length required by company policy?",
         json.dumps(["8 characters", "10 characters", "12 characters", "16 characters"]),
         "12 characters", 5,
         "The company policy requires a minimum of 12 characters for all passwords.",
         "Easy", "Password Security", 1),
        ("true_false", "Employees should reuse the same password across multiple company systems.",
         json.dumps(["True", "False"]), "False", 5,
         "Reusing passwords increases risk; each system should have unique credentials.",
         "Easy", "Password Security", 2),
        ("multiple_choice", "Which tool should employees use to store their passwords?",
         json.dumps(["A browser's built-in password manager", "The company-approved password manager",
                     "A physical notebook", "A personal spreadsheet"]),
         "The company-approved password manager", 5,
         "Only the company-approved password manager meets security standards.",
         "Easy", "Password Security", 3),
        ("multiple_choice", "What should you do immediately after discovering a compromised password?",
         json.dumps(["Change it right away", "Report it to IT security", "Use a stronger password",
                     "Wait to see if it resolves itself"]),
         "Report it to IT security", 5,
         "Reporting allows security to investigate and protect other employees.",
         "Medium", "Password Security", 4),
        ("multiple_select", "Which of the following are characteristics of a strong password? (Select all that apply)",
         json.dumps(["At least 12 characters", "Contains dictionary words", "Mix of uppercase and lowercase",
                     "Mix of letters, numbers, and special characters"]),
         json.dumps(["At least 12 characters", "Mix of uppercase and lowercase", "Mix of letters, numbers, and special characters"]),
         5, "Strong passwords use length, complexity, and character variety.", "Medium", "Password Security", 5),
    ]

    # Phishing Awareness questions
    questions_ph = [
        ("multiple_choice", "Which action is safest when receiving a suspicious email?",
         json.dumps(["Open the attachment to inspect it", "Reply to the sender for clarification",
                     "Report the email using the company reporting procedure", "Forward it to colleagues"]),
         "Report the email using the company reporting procedure", 5,
         "Suspicious emails should be reported through approved channels so the security team can investigate.",
         "Easy", "Phishing Awareness", 1),
        ("true_false", "Urgent language demanding immediate action is a common sign of phishing.",
         json.dumps(["True", "False"]), "True", 5,
         "Phishing emails often use urgency to pressure victims into acting quickly.",
         "Easy", "Phishing Awareness", 2),
        ("multiple_select", "Which of the following are signs of a phishing email? (Select all that apply)",
         json.dumps(["Suspicious links", "Urgent language demanding immediate action", "Sender address does not match claimed company",
                     "Normal internal announcement from HR"]),
         json.dumps(["Suspicious links", "Urgent language demanding immediate action", "Sender address does not match claimed company"]),
         5, "Phishing emails use suspicious links, urgency, and spoofed sender addresses.",
         "Medium", "Phishing Awareness", 3),
        ("multiple_choice", "What should you do if you accidentally clicked a link in a suspected phishing email?",
         json.dumps(["Nothing — just be more careful next time", "Close the browser and report the incident",
                     "Enter a test password to see if it works", "Download an antivirus scan"]),
         "Close the browser and report the incident", 5,
         "Reporting allows the security team to contain and investigate potential compromise.",
         "Hard", "Phishing Awareness", 4),
    ]

    # Social Engineering questions
    questions_se = [
        ("multiple_choice", "Which social engineering technique involves creating a false scenario to obtain information?",
         json.dumps(["Baiting", "Pretexting", "Tailgating", "Spear phishing"]),
         "Pretexting", 5,
         "Pretexting uses a fabricated scenario to deceive victims into revealing information.",
         "Medium", "Social Engineering", 1),
        ("true_false", "Tailgating refers to following an authorised person into a restricted area.",
         json.dumps(["True", "False"]), "True", 5,
         "Tailgating is a physical social engineering technique.",
         "Easy", "Social Engineering", 2),
        ("multiple_choice", "What is the best defence against social engineering attacks?",
         json.dumps(["Sharing information quickly to be helpful", "Verifying identity through a secondary channel",
                     "Ignoring all external communications", "Memorising everyone's name"]),
         "Verifying identity through a secondary channel", 5,
         "Always verify identity through an independent, trusted channel.",
         "Medium", "Social Engineering", 3),
    ]

    # Device Security questions
    questions_ds = [
        ("multiple_choice", "What should you do when leaving your workstation unattended?",
         json.dumps(["Just lock the screen", "Lock the screen or shut down", "Leave it as is", "Log out completely"]),
         "Lock the screen or shut down", 5,
         "Locking or shutting down prevents unauthorised access to your workstation.",
         "Easy", "Device Security", 1),
        ("true_false", "Full-disk encryption is only necessary for laptops, not desktop computers.",
         json.dumps(["True", "False"]), "False", 5,
         "All company devices should use full-disk encryption.",
         "Easy", "Device Security", 2),
        ("multiple_choice", "What is the first step when a company device is lost or stolen?",
         json.dumps(["Try to locate it using GPS", "Immediately report it to IT security", "Buy a replacement", "Wait a day to see if it turns up"]),
         "Immediately report it to IT security", 5,
         "Immediate reporting allows IT to remotely wipe and investigate.",
         "Easy", "Device Security", 3),
    ]

    # Incident Reporting questions
    questions_ir = [
        ("multiple_choice", "Within how many hours should a suspected security incident be reported?",
         json.dumps(["24 hours", "8 hours", "2 hours", "Immediately"]),
         "2 hours", 5,
         "Incidents must be reported within 2 hours to allow rapid response.",
         "Medium", "Incident Reporting", 1),
        ("true_false", "You should attempt to investigate a security incident yourself before reporting it.",
         json.dumps(["True", "False"]), "False", 5,
         "Investigation should be left to the security team; employees should only report.",
         "Easy", "Incident Reporting", 2),
        ("multiple_choice", "Which of the following constitutes a reportable security incident?",
         json.dumps(["All of the above", "Lost company device", "Suspected phishing attempt", "Unusual network activity"]),
         "All of the above", 5,
         "All of these events should be reported as potential security incidents.",
         "Easy", "Incident Reporting", 3),
    ]

    # Final assessment questions (mix of all topics)
    questions_final = [
        ("multiple_choice", "What should you do after discovering a suspected phishing email?",
         json.dumps(["Open the attachment to investigate", "Reply to the sender", "Report it using the company reporting procedure", "Forward to colleagues"]),
         "Report it using the company reporting procedure", 5,
         "Reporting allows the security team to investigate and protect other employees.",
         "Easy", "Phishing Awareness", 1),
        ("true_false", "Reusing passwords across company systems is acceptable if they are strong passwords.",
         json.dumps(["True", "False"]), "False", 5,
         "Each system must have a unique password to limit blast radius.",
         "Easy", "Password Security", 2),
        ("multiple_choice", "Which is NOT a characteristic of a strong password?",
         json.dumps(["At least 12 characters", "Contains only lowercase letters", "Mix of character types", "Unique across systems"]),
         "Contains only lowercase letters", 5,
         "Strong passwords use length, complexity, and character variety.",
         "Medium", "Password Security", 3),
        ("true_false", "Social engineering only targets digital systems, not physical access.",
         json.dumps(["True", "False"]), "False", 5,
         "Social engineering includes physical techniques like tailgating.",
         "Hard", "Social Engineering", 4),
        ("multiple_choice", "What is the first action when handling a lost company device?",
         json.dumps(["Search nearby areas", "Immediately report to IT security", "Assume it will be found", "Buy a replacement"]),
         "Immediately report to IT security", 5,
         "Immediate reporting enables rapid containment and device wipe.",
         "Medium", "Device Security", 5),
        ("multiple_select", "Which of the following are signs of phishing? (Select all that apply)",
         json.dumps(["Suspicious links", "Urgent language demanding immediate action", "Normal internal announcement", "Unexpected attachments"]),
         json.dumps(["Suspicious links", "Urgent language demanding immediate action", "Unexpected attachments"]),
         5, "Phishing relies on urgency, suspicious links, and unexpected attachments.",
         "Medium", "Phishing Awareness", 6),
        ("true_false", "All company devices should use full-disk encryption.",
         json.dumps(["True", "False"]), "True", 5,
         "Encryption protects data from interception and unauthorised access.",
         "Easy", "Device Security", 7),
        ("multiple_choice", "What should you do if you accidentally clicked a link in a suspected phishing email?",
         json.dumps(["Nothing", "Close the browser and report the incident", "Enter a test password", "Download antivirus"]),
         "Close the browser and report the incident", 5,
         "Reporting allows the security team to contain and investigate.",
         "Hard", "Phishing Awareness", 8),
    ]

    # Seed questions into assessments
    all_questions = [
        (assess1_1.id, questions_ps),
        (assess1_2.id, questions_ph),
        (assess1_3.id, questions_se),
        (assess1_4.id, questions_ds),
        (assess1_5.id, questions_ir),
        (assess1_final.id, questions_final),
    ]

    for assessment_id, q_list in all_questions:
        for idx, (qtype, qtext, opts, correct, pts, expl, diff, topic, order) in enumerate(q_list, 1):
            q = Question(
                assessment_id=assessment_id,
                type=qtype,
                question=qtext,
                options=opts,
                correct_answer=correct,
                points=pts,
                explanation=expl,
                difficulty=diff,
                topic=topic,
                order=order,
            )
            db.add(q)

    # --- Course 2: Data Protection and Privacy ---
    course2 = Course(
        title="Data Protection and Privacy",
        slug="data-protection-and-privacy",
        description="Understand data protection regulations, privacy principles, and how to handle personal data responsibly.",
        objectives="Understand GDPR principles\nHandle personal data securely\nIdentify data breach reporting requirements\nApply data minimisation principles",
        category="Data Protection",
        difficulty="Intermediate",
        duration="30 min",
        published=True,
        mandatory=True,
        passing_score=75,
        start_date=None,
        due_date=None,
        requires_module_completion=True,
    )
    db.add(course2)
    db.commit()

    assess2_1 = Assessment(
        course_id=course2.id,
        title="Data Protection Fundamentals Quiz",
        passing_score=75,
        max_attempts=3,
        retakes_allowed=True,
        published=True,
    )
    db.add(assess2_1)
    db.commit()

    module2_1 = Module(
        course_id=course2.id,
        title="Data Protection Fundamentals",
        content="# Data Protection and Privacy\n\n**GDPR Key Principles:**\n\n1. **Lawfulness, fairness, transparency** — Data must be processed legally and transparently.\n2. **Purpose limitation** — Data collected for specified, explicit purposes only.\n3. **Data minimisation** — Only collect the minimum data necessary.\n4. **Accuracy** — Keep personal data accurate and up to date.\n5. **Storage limitation** — Retain data only as long as necessary.\n6. **Integrity and confidentiality** — Secure data against unauthorised access.\n7. **Accountability** — Demonstrate compliance with all principles.\n\n**Personal data** includes any information that can identify an individual: names, email addresses, ID numbers, location data, etc.\n\n**Data breach reporting:** Suspected or confirmed breaches must be reported to the Data Protection Officer within 24 hours.",
        content_type="markdown",
        order=1,
        assessment_id=assess2_1.id,
    )
    db.add(module2_1)

    questions_dp = [
        ("multiple_choice", "Under GDPR, how long should employee personal data be retained after termination?",
         json.dumps(["Indefinitely", "7 years", "As long as there is a documented business need", "Until the next payroll cycle"]),
         "As long as there is a documented business need", 5,
         "Data should be retained only as long as there is a legitimate business need.",
         "Medium", "Compliance", 1),
        ("true_false", "Personal data must be encrypted both in transit and at rest.",
         json.dumps(["True", "False"]), "True", 5,
         "Encryption protects data from interception and unauthorised access.",
         "Easy", "Data Protection", 2),
        ("multiple_choice", "Which principle requires collecting only the minimum data necessary?",
         json.dumps(["Accuracy", "Data minimisation", "Storage limitation", "Accountability"]),
         "Data minimisation", 5,
         "Data minimisation ensures only necessary data is collected.",
         "Medium", "Compliance", 3),
        ("multiple_select", "Which of the following are GDPR rights? (Select all that apply)",
         json.dumps(["Right to be forgotten", "Right to data portability", "Right to unlimited storage", "Right to erasure"]),
         json.dumps(["Right to be forgotten", "Right to data portability", "Right to erasure"]),
         5, "GDPR grants individuals rights to access, port, and delete their data.",
         "Hard", "Compliance", 4),
    ]

    for idx, (qtype, qtext, opts, correct, pts, expl, diff, topic, order) in enumerate(questions_dp, 1):
        q = Question(
            assessment_id=assess2_1.id,
            type=qtype,
            question=qtext,
            options=opts,
            correct_answer=correct,
            points=pts,
            explanation=expl,
            difficulty=diff,
            topic=topic,
            order=order,
        )
        db.add(q)

    # --- Course 3: Health and Safety (Optional) ---
    course3 = Course(
        title="Workplace Health and Safety",
        slug="workplace-health-and-safety",
        description="Core health and safety principles for the workplace, including emergency procedures, hazard identification, and incident reporting.",
        objectives="Identify common workplace hazards\nFollow emergency evacuation procedures\nReport safety incidents correctly\nUnderstand personal protective equipment requirements",
        category="Health & Safety",
        difficulty="Beginner",
        duration="25 min",
        published=True,
        mandatory=False,
        passing_score=70,
    )
    db.add(course3)
    db.commit()

    assess3_1 = Assessment(
        course_id=course3.id,
        title="Health and Safety Assessment",
        passing_score=70,
        max_attempts=3,
        retakes_allowed=True,
        published=True,
    )
    db.add(assess3_1)
    db.commit()

    module3_1 = Module(
        course_id=course3.id,
        title="Workplace Safety Fundamentals",
        content="# Workplace Health and Safety\n\n**Emergency Evacuation:**\n- Know the nearest exit route from your work area\n- Follow floor warden instructions during evacuations\n- Assemble at the designated muster point\n- Do not use elevators during fire emergencies\n\n**Hazard Reporting:**\n- Report hazards immediately to your supervisor or HSE team\n- Use the digital hazard report form on the company portal\n- Near misses must also be reported — they predict future incidents\n\n**Personal Protective Equipment (PPE):**\n- Hard hats in construction/warehouse areas\n- Safety glasses in labs\n- Steel-toed boots in industrial zones",
        content_type="markdown",
        order=1,
        assessment_id=assess3_1.id,
    )
    db.add(module3_1)

    questions_hs = [
        ("multiple_choice", "What should you do during a fire alarm in the office?",
         json.dumps(["Keep working — it might be a drill", "Evacuate immediately using the nearest exit",
                     "Wait for your supervisor's instructions", "Go to the nearest window"]),
         "Evacuate immediately using the nearest exit", 5,
         "Fire alarms require immediate evacuation using designated exits.",
         "Easy", "Health & Safety", 1),
        ("true_false", "Near-miss incidents should not be reported since nothing happened.",
         json.dumps(["True", "False"]), "False", 5,
         "Near misses are important data that predict and prevent actual incidents.",
         "Easy", "Health & Safety", 2),
        ("multiple_choice", "Which of the following is NOT a proper emergency response?",
         json.dumps(["Using stairs instead of elevators", "Proceeding to the muster point",
                     "Stopping to take photos", "Following warden instructions"]),
         "Stopping to take photos", 5,
         "Emergency responses prioritise safety over personal activities.",
         "Medium", "Health & Safety", 3),
    ]

    for idx, (qtype, qtext, opts, correct, pts, expl, diff, topic, order) in enumerate(questions_hs, 1):
        q = Question(
            assessment_id=assess3_1.id,
            type=qtype,
            question=qtext,
            options=opts,
            correct_answer=correct,
            points=pts,
            explanation=expl,
            difficulty=diff,
            topic=topic,
            order=order,
        )
        db.add(q)

    db.commit()
