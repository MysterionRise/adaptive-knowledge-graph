# Adaptive Knowledge Graph - 2026 Roadmap

**Vision:** Pivot from Education PoC to the premier **Professional Certification & Adult Retraining Platform**. Empowering adults to switch careers through verified, skill-based micro-credentials derived from open academic content.

**Last Updated:** December 12, 2025
**Status:** Strategic Pivot Execution

---

## Executive Summary

### Strategic Pivot (December 2025)
The project is evolving from a general-purpose study tool into a **Professional Certification Engine**.
- **User Focus**: Adult Learners, Career Switchers, Corporate Retraining.
- **Value Prop**: "Turn Open Knowledge into Verifiable Careers".
- **Key Deliverable**: Cryptographically signed Career Certificates (e.g., "Certified Pre-Nursing Competency").

### Current State
- ✅ **Tech Stack**: Solid KG-RAG foundation (Neo4j/OpenSearch/LLM).
- ⚠️ **Gap**: Lacks strict assessment, identity verification, and multi-book "Career Paths".

### 2026 Vision: The "Career Graph"
- 🎯 **Career Paths**: Abstract layer grouping "Algebra", "Biology", "Psychology" into "Nursing Prep".
- 🎯 **Certification**: Timed, proctored-style exams with verifiable digital credentials.
- 🎯 **Enterprise**: B2B dashboards for companies to track employee upskilling ROI.
- 🎯 **Compliance**: Identity verification and strict audit logging for issued certs.

---

## Q1 2026: Foundation & Scale (Jan-Mar)

**Theme:** Stabilize PoC, add multi-book support, improve performance

### P0: Critical Features
**Goal:** Production-ready single-deployment system

#### 1.1 Career Path Architecture (8 weeks)
**Why:** Adults don't want "Books"; they want "Jobs". We must group content by Career Goal.

**Features:**
- [ ] **Career Path Meta-Graph**:
  - Define paths: "Nursing Prep", "Data Science Foundation", "Solar Technician".
  - Map O*NET Skills to OpenStax Concepts.
  - Cross-book dependencies (e.g., Math reqs for Chemistry).

**Deliverables:**
- `CareerPath` nodes in Neo4j.
- `Competency` nodes bridging Academic Concepts to Job Skills.
- Frontend: "Choose your Career" onboarding.

**Effort:** 2 engineers × 8 weeks = 320 hours

---

#### 1.2 Certification Engine & Identity (6 weeks)
**Why:** Certifications are worthless without verification and strict testing.

**Features:**
- [ ] **Strict Assessment Mode**:
  - Timed exams.
  - Full-screen proctoring hook (browser lock/warnings).
  - No hints/chat allowed.
- [ ] **Digital Credentials**:
  - Generate signed JSON-LD / PDF Certificates.
  - Unique verification URL (e.g., `cert.verify/uuid`).

**Deliverables:**
- Certification Service (FastAPI).
- PDF Generator.
- Verification UI.

**Effort:** 2 engineers × 6 weeks = 480 hours

---

### P1: Corporate Enterprise Dashboard (6 weeks)
**Why:** Companies funding retraining need visibility into ROI and Skill Gaps.

#### 1.3 Enterprise Tenant Portal
**Features:**
- [ ] **Cohort Management**: "Fall 2026 Reskilling Class".
- [ ] **Skill Gap Analysis**:
  - Pre-assessment vs. Post-assessment deltas.
  - "Time to Proficiency" metrics.
- [ ] **Compliance Reporting**:
  - Downloadable audit logs for HR.

**Technical:**
- Multi-tenancy support (TenantID in all tables).
- Role-based Access: `OrgAdmin`, `Manager`, `Employee`.

**Deliverables:**
- Enterprise Dashboard.
- CSV/PDF Export Engine.

**Effort:** 2 engineers × 6 weeks = 480 hours

---

### P2: Infrastructure & DevOps (4 weeks)
**Why:** PoC runs on single machine, need cloud deployment

#### 1.5 Kubernetes Deployment
**Features:**
- [ ] Dockerize all services
  - Backend API (FastAPI)
  - Frontend (Next.js)
  - Neo4j (StatefulSet)
  - Qdrant (StatefulSet)
  - PostgreSQL (StatefulSet)
  - Redis (cache)

- [ ] Helm charts for deployment
- [ ] Horizontal pod autoscaling (HPA)
- [ ] Health checks and readiness probes
- [ ] Secrets management (Vault or K8s secrets)
- [ ] Monitoring (Prometheus + Grafana)
- [ ] Logging (ELK stack or Loki)

**Technical:**
- AWS EKS or GCP GKE
- Load balancer (ALB/NLB)
- Autoscaling: 2-20 API pods
- Database backups (daily)
- Disaster recovery plan

**Deliverables:**
- Kubernetes manifests
- Helm chart
- CI/CD pipeline (GitHub Actions)
- Monitoring dashboards
- Runbook for ops team

**Effort:** 1 DevOps engineer × 4 weeks = 160 hours

---

### Q1 Milestones
- ✅ **Jan 31**: Multi-book support (5 books)
- ✅ **Feb 28**: Student models live (BKT + IRT)
- ✅ **Mar 31**: Teacher dashboard beta
- ✅ **Mar 31**: Kubernetes deployment on staging

**Total Q1 Effort:** ~1,680 hours (4-5 engineers)

---

## Q2 2026: Intelligent Features (Apr-Jun)

**Theme:** Advanced AI, personalization, assessment generation

### P0: Assessment Generation (8 weeks)

#### 2.1 Automatic Quiz Creation
**Why:** Manually creating quizzes is time-consuming

**Features:**
- [ ] LLM-powered MCQ generation
  - Input: Concept + difficulty level
  - Output: 4-choice MCQ with distractor analysis
  - Quality control: Human-in-the-loop validation

- [ ] Question types
  - Multiple choice (4 options)
  - True/False
  - Fill-in-the-blank
  - Short answer (auto-graded with LLM)

- [ ] Difficulty calibration
  - Generate easy/medium/hard versions
  - Calibrate with IRT after student responses

- [ ] Question bank
  - Store in PostgreSQL (`questions` table)
  - Tag with concepts, difficulty, bloom level
  - Version control for edits

**Technical:**
- Prompt engineering for quiz generation
- Few-shot examples from OpenStax end-of-chapter questions
- LLM evaluation (GPT-4 or Claude for generation + scoring)
- Human review workflow (flagging low-quality questions)

**Deliverables:**
- Quiz generation API endpoint
- Question bank schema
- Frontend: Quiz creator for teachers
- Frontend: Quiz-taking interface for students
- Quality metrics dashboard

**Effort:** 2 engineers × 8 weeks = 640 hours

---

#### 2.2 Conversational Tutor (6 weeks)
**Why:** Current chat is one-shot Q&A, not conversational

**Features:**
- [ ] Multi-turn dialogue
  - Remember conversation history
  - Follow-up questions
  - Clarifications

- [ ] Socratic method
  - Ask guiding questions instead of giving answers
  - Scaffold learning
  - Encourage critical thinking

- [ ] Personalized explanations
  - Adapt complexity to student level
  - Use student's prior knowledge
  - Reference previously learned concepts

- [ ] Session management
  - Save/resume conversations
  - Export transcripts
  - Teacher review of chat logs

**Technical:**
- Conversation state in Redis (session_id → messages)
- Prompt: Include student mastery levels
- RAG: Pull from concept neighborhood (not just query match)
- WebSocket for streaming responses

**Deliverables:**
- Conversational API (stateful)
- Frontend: Enhanced chat with history
- Session persistence
- Teacher chat review UI

**Effort:** 2 engineers × 6 weeks = 480 hours

---

### P1: Analytics & Insights (6 weeks)

#### 2.3 Learning Analytics
**Features:**
- [ ] Student dashboards
  - Personal progress charts
  - Strengths/weaknesses heatmap
  - Time spent per concept
  - Predicted mastery timeline

- [ ] Class analytics
  - Class average vs. individual
  - Concept difficulty ranking (by class performance)
  - Engagement metrics (logins, questions asked, quizzes completed)

- [ ] Predictive models
  - Predict final grade from Week 4 data
  - Early warning system for at-risk students
  - Recommend interventions

- [ ] A/B testing framework
  - Compare teaching strategies
  - Compare LLM prompts
  - Compare learning path algorithms

**Technical:**
- Data warehouse (Postgres or BigQuery)
- ETL pipeline (Airflow)
- ML models (scikit-learn)
- Visualization (Recharts or D3.js in frontend)

**Deliverables:**
- Analytics database schema
- ETL jobs
- Predictive models
- Dashboards for students & teachers
- A/B testing UI

**Effort:** 2 engineers × 6 weeks = 480 hours

---

### P2: Accessibility & Internationalization (4 weeks)

#### 2.4 Accessibility (WCAG 2.1 AA)
**Features:**
- [ ] Screen reader support
- [ ] Keyboard navigation
- [ ] High contrast mode
- [ ] Font size controls
- [ ] Alt text for all images
- [ ] ARIA labels
- [ ] Caption support for videos (if added)

**Deliverables:**
- Accessibility audit report
- Remediation plan
- Automated accessibility tests (Pa11y)

**Effort:** 1 engineer × 4 weeks = 160 hours

---

#### 2.5 Internationalization (i18n)
**Why:** Expand beyond English-speaking markets

**Features:**
- [ ] Multi-language UI (Spanish, French, Mandarin)
- [ ] RTL support (Arabic, Hebrew)
- [ ] Locale-specific formatting (dates, numbers)

**Technical:**
- i18n framework (next-i18next)
- Translation management (Crowdin)
- Locale detection

**Deliverables:**
- i18n infrastructure
- Spanish translation (pilot)
- Language switcher in UI

**Effort:** 1 engineer × 4 weeks = 160 hours

---

### Q2 Milestones
- ✅ **Apr 30**: Auto quiz generation live
- ✅ **May 31**: Conversational tutor beta
- ✅ **Jun 30**: Analytics dashboards v1
- ✅ **Jun 30**: Spanish UI pilot

**Total Q2 Effort:** ~1,920 hours (4-5 engineers)

---

## Q3 2026: Scale & Pilot (Jul-Sep)

**Theme:** Pilot with real schools, refine based on feedback

### P0: Pilot Program (12 weeks)

#### 3.1 School Pilot (3 schools, 500 students)
**Partners:**
- High school (Biology, Chemistry)
- Community college (Algebra, Calculus)
- University (Physics, Economics)

**Goals:**
- Validate effectiveness (pre/post test scores)
- Measure engagement (DAU, time-on-platform)
- Collect feedback (surveys, interviews)
- Identify bugs and UX issues

**Metrics:**
- Student outcomes: +10% average score improvement
- Engagement: 3× usage vs. control group
- Satisfaction: 4.5/5 average rating
- Retention: 80% active after 8 weeks

**Activities:**
- Week 1-2: Onboarding & training
- Week 3-10: Active use
- Week 11-12: Analysis & iteration

**Deliverables:**
- Pilot playbook
- Training materials for teachers
- Support documentation
- Feedback surveys
- Pilot report with recommendations

**Effort:** 1 PM × 12 weeks + 2 engineers (support) = 640 hours

---

#### 3.2 Enterprise Features (8 weeks)
**Why:** Schools need admin tools, SSO, compliance

**Features:**
- [ ] Single Sign-On (SSO)
  - SAML 2.0 (for Google Workspace, Microsoft)
  - OAuth 2.0 (GitHub, Canvas LMS)

- [ ] Institution admin
  - Manage multiple classes
  - Assign licenses
  - Usage reports (billing metrics)

- [ ] FERPA compliance
  - Student data encryption
  - Audit logs
  - Data retention policies
  - Parental consent workflows

- [ ] LTI integration
  - Integrate with Canvas, Blackboard, Moodle
  - Grade passback
  - Deep linking

**Technical:**
- Identity provider integration
- Role hierarchy (super-admin, admin, teacher, student)
- Audit log table in PostgreSQL
- LTI 1.3 implementation

**Deliverables:**
- SSO configuration
- Admin dashboard
- Compliance documentation
- LTI plugin for Canvas

**Effort:** 2 engineers × 8 weeks = 640 hours

---

### P1: Mobile Apps (12 weeks)

#### 3.3 iOS & Android Apps
**Why:** 60% of students prefer mobile learning

**Features:**
- [ ] Native apps (React Native or Flutter)
- [ ] Offline mode
  - Download textbook chapters
  - Sync progress when online
- [ ] Push notifications
  - New quiz available
  - Concept mastered
  - Streaks (gamification)

**Technical:**
- React Native (same codebase for iOS + Android)
- Offline-first architecture (PouchDB + CouchDB sync)
- Push notifications (Firebase Cloud Messaging)

**Deliverables:**
- iOS app (App Store)
- Android app (Google Play)
- Offline sync infrastructure

**Effort:** 2 mobile engineers × 12 weeks = 960 hours

---

### P2: Gamification (4 weeks)

#### 3.4 Engagement Features
**Features:**
- [ ] Points & badges
- [ ] Leaderboards (opt-in for students)
- [ ] Streaks (login daily)
- [ ] Achievements (complete all Biology concepts)
- [ ] Levels (Novice → Expert)

**Deliverables:**
- Gamification schema
- API endpoints
- Frontend: Badges & leaderboard UI

**Effort:** 1 engineer × 4 weeks = 160 hours

---

### Q3 Milestones
- ✅ **Jul 31**: Pilot kickoff with 3 schools
- ✅ **Aug 31**: Mobile apps in beta (TestFlight, Google Play Beta)
- ✅ **Sep 30**: Pilot complete, report published
- ✅ **Sep 30**: Enterprise features live

**Total Q3 Effort:** ~2,400 hours (5-6 engineers + 1 PM)

---

## Q4 2026: Production & Revenue (Oct-Dec)

**Theme:** Go-to-market, revenue generation, scaling to 10K+ students

### P0: Go-to-Market (12 weeks)

#### 4.1 Pricing Model
**Freemium Tiers:**

**Free Tier:**
- 1 book (Biology)
- Basic Q&A chat
- 10 quiz questions/week
- No teacher dashboard

**Student Tier ($5/month or $50/year):**
- All 10 books
- Unlimited Q&A
- Unlimited quizzes
- Progress tracking
- Mobile apps

**Teacher Tier ($15/month or $150/year):**
- All student features
- Teacher dashboard
- 1 class (up to 30 students)
- Content authoring
- Analytics

**Institution Tier ($500/year per 100 students):**
- All teacher features
- Unlimited classes
- SSO integration
- LTI integration
- Dedicated support
- SLA (99.9% uptime)
- Custom branding

**Revenue Projections:**
- Year 1: 1,000 paid students × $50 = $50K
- Year 1: 50 teachers × $150 = $7.5K
- Year 1: 5 institutions × $5K = $25K
- **Total Year 1 Revenue: $82.5K**

---

#### 4.2 Marketing & Sales (Ongoing)
**Channels:**
- Content marketing (blog, case studies)
- SEO (rank for "adaptive learning biology")
- Social media (Twitter/X, LinkedIn for teachers)
- Conference presentations (NSTA, ISTE)
- Partnership with OpenStax
- Affiliate program (teachers get $10 per referral)

**Deliverables:**
- Marketing website (WordPress or Webflow)
- Case studies from pilot schools
- Conference booth materials
- Partnership agreement with OpenStax

**Effort:** 1 marketing hire + 1 PM = ongoing

---

### P1: Advanced AI Features (8 weeks)

#### 4.3 Multimodal Learning
**Features:**
- [ ] Image-based questions
  - Upload diagram, get explanation
  - OCR for handwritten work

- [ ] Video integration
  - Khan Academy video embedding
  - Concept-tagged video segments

- [ ] Speech-to-text
  - Voice-based Q&A
  - Oral assessments

**Technical:**
- Vision-language model (GPT-4V or LLaVA)
- Video chunking and embedding
- Speech recognition (Whisper API)

**Deliverables:**
- Image upload in chat
- Video library
- Voice input UI

**Effort:** 2 engineers × 8 weeks = 640 hours

---

#### 4.4 Collaborative Learning
**Features:**
- [ ] Study groups
  - Students can form groups
  - Shared chat rooms
  - Group quizzes

- [ ] Peer review
  - Students review each other's answers
  - Upvote/downvote helpful explanations

- [ ] Discussion forums
  - Per-concept threads
  - Teacher moderation

**Technical:**
- Group management schema
- WebSocket for real-time chat
- Forum backend (or integrate Discourse)

**Deliverables:**
- Group creation UI
- Group chat
- Discussion forum

**Effort:** 2 engineers × 8 weeks = 640 hours

---

### P2: Research & Publication (Ongoing)

#### 4.5 Academic Research
**Goals:**
- Publish findings from pilot program
- Partner with education researchers
- Validate efficacy of KG-aware RAG

**Activities:**
- IRB approval for research study
- Data anonymization and sharing
- Co-author papers with university partners
- Present at ACM Learning @ Scale, EDM conferences

**Deliverables:**
- Research paper (draft)
- Conference submissions
- Open dataset (anonymized)

**Effort:** 1 researcher + 1 engineer (data prep) = 320 hours

---

### Q4 Milestones
- ✅ **Oct 31**: Marketing website live
- ✅ **Nov 30**: 1,000 paid users
- ✅ **Dec 31**: Production deployment (10K+ users)
- ✅ **Dec 31**: First research paper submitted

**Total Q4 Effort:** ~1,600 hours (4-5 engineers + marketing + PM)

---

## 2026 Summary

### Total Engineering Effort
- **Q1**: 1,680 hours (4-5 engineers)
- **Q2**: 1,920 hours (4-5 engineers)
- **Q3**: 2,400 hours (5-6 engineers + 1 PM)
- **Q4**: 1,600 hours (4-5 engineers + marketing + PM)
- **Total**: ~7,600 hours

### Team Size
- **Engineers**: 4-6 (full-time)
- **Product Manager**: 1 (full-time)
- **DevOps**: 1 (part-time or contractor)
- **Marketing/Sales**: 1 (full-time in Q4)
- **Researcher**: 1 (part-time)

### Budget Estimate
- **Engineering**: 6 engineers × $120K = $720K
- **PM**: 1 PM × $110K = $110K
- **Marketing**: 1 marketing × $80K = $80K
- **Infrastructure**: AWS/GCP = $50K/year
- **Tools**: Licenses, SaaS = $20K
- **Total 2026 Budget**: **~$980K**

### Revenue Target
- **Year 1**: $82.5K (ramp-up)
- **Year 2 (2027)**: $500K (10K students, 500 teachers, 50 institutions)
- **Year 3 (2028)**: $2M (scale to 100K students)

### Key Risks
1. **Adoption Risk**: Schools slow to adopt new technology
   - Mitigation: Free pilot program, easy onboarding
2. **Competition**: Khan Academy, Duolingo, Coursera
   - Mitigation: Unique KG-aware RAG differentiation
3. **Technical Risk**: Scaling to 10K users
   - Mitigation: Load testing, cloud infrastructure
4. **Regulatory Risk**: FERPA, COPPA compliance
   - Mitigation: Legal review, compliance audit

---

## Beyond 2026: Long-Term Vision

### 2027-2028 Goals
- **100K students** across 50+ schools
- **All OpenStax subjects** (30+ books)
- **AI tutor speaks 10 languages**
- **B2B SaaS** for publishers (white-label KG platform)
- **Research lab** for learning sciences
- **Exit strategy**: Acquisition by EdTech giant (Pearson, McGraw Hill) or IPO

### Moonshot Ideas
- **VR/AR learning**: Walk through 3D cell structure
- **Brain-computer interface**: Measure cognitive load in real-time
- **AGI tutor**: GPT-5-powered personalized teacher
- **Global learning graph**: Connect knowledge across all subjects, all languages

---

## Success Metrics (2026)

| Metric | Q1 Target | Q2 Target | Q3 Target | Q4 Target |
|--------|-----------|-----------|-----------|-----------|
| **Students** | 100 | 250 | 500 | 1,000 |
| **Teachers** | 10 | 25 | 50 | 100 |
| **Books Supported** | 5 | 10 | 10 | 10 |
| **Concepts in Graph** | 500 | 1,000 | 1,000 | 1,000 |
| **Questions in Bank** | 0 | 500 | 1,000 | 2,000 |
| **Uptime (SLA)** | 95% | 99% | 99.5% | 99.9% |
| **API Latency (p95)** | 2s | 1s | 500ms | 500ms |
| **Revenue** | $5K | $15K | $30K | $82.5K |
| **NPS Score** | N/A | 30 | 40 | 50 |

---

## Appendix: Technology Evolution

### Current Stack (2025)
- **Frontend**: Next.js 14, TypeScript, Tailwind
- **Backend**: FastAPI, Python 3.11-3.13
- **Database**: Neo4j (graph), OpenSearch (vectors)
- **LLM**: Llama 3.1 8B (local, 4-bit)
- **Infrastructure**: Single VPS or local machine

### 2026 Stack (Proposed)
- **Frontend**: Next.js 14 + React Native (mobile)
- **Backend**: FastAPI (scale to microservices if needed)
- **Databases**:
  - Neo4j (graph)
  - OpenSearch (vectors)
  - PostgreSQL (student data, assessments)
  - Redis (cache, sessions)
- **LLM**:
  - Local: Llama 3.1 8B (student Q&A)
  - Cloud: GPT-4 or Claude 3.5 (quiz generation, grading)
- **Infrastructure**:
  - Kubernetes on AWS EKS or GCP GKE
  - Autoscaling: 2-20 pods
  - CDN: Cloudflare
  - Monitoring: Prometheus + Grafana
  - Logging: Loki or ELK

### Future Stack (2027+)
- **Microservices**: Split backend into services (auth, graph, rag, student, assessment)
- **Event streaming**: Kafka for real-time analytics
- **Data warehouse**: BigQuery or Snowflake
- **MLOps**: Kubeflow for model training/deployment
- **Edge computing**: Run LLM inference on edge for latency

---

**End of Roadmap**

**Document Ownership:**
- **Product**: Product Manager
- **Engineering**: Engineering Lead
- **Updates**: Quarterly review, adjust based on pilot results

**Questions?** Reach out to team@adaptive-kg.edu
