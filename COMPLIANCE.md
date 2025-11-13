# Compliance & Privacy Documentation

## OpenStax Content Usage

### License
OpenStax Biology 2e is licensed under **Creative Commons Attribution License 4.0 (CC BY 4.0)**.
- License URL: https://creativecommons.org/licenses/by/4.0/
- Content URL: https://openstax.org/details/books/biology-2e

### Our Compliance Measures

#### ✅ Attribution
- **UI Footer**: Every page displays: "Content adapted from OpenStax Biology 2e, licensed under CC BY 4.0"
- **API Responses**: All content responses include `attribution` field
- **Exports**: RDF/Turtle exports include metadata with attribution
- **Documentation**: README and LICENSE clearly state OpenStax attribution

#### ✅ No Model Training
- We do **NOT** fine-tune or train models on OpenStax content
- Content is used only for:
  - Information retrieval (RAG)
  - Concept extraction (transformative use)
  - Graph construction (derivative work with attribution)

#### ✅ No Unauthorized Ingestion
OpenStax states: "do not train or ingest into LLM offerings without permission"

**Our approach**:
- **Local mode (default)**: All LLM processing happens on user's hardware; no external ingestion
- **Remote mode (opt-in)**:
  - Only **transformed excerpts** sent to OpenRouter (e.g., extracted concepts, not raw passages)
  - Users must explicitly enable via `PRIVACY_LOCAL_ONLY=false`
  - Minimal context in prompts (typically <500 tokens)
  - Prompts are **transformative** (e.g., "Is concept A a prerequisite for B?")

#### ✅ Commercial Use
CC BY 4.0 allows commercial use **with attribution**. This PoC:
- Attributes OpenStax in all outputs
- Can be used commercially if attribution is maintained
- Does not claim ownership of OpenStax content

### Trademark
> OpenStax™ is a registered trademark of Rice University. This project is not affiliated with, sponsored by, or endorsed by OpenStax or Rice University.

---

## Privacy & Data Protection

### Privacy-First Architecture

#### Local-Only Mode (Default)
```bash
PRIVACY_LOCAL_ONLY=true  # Default setting
```

When enabled:
- ❌ No data sent to OpenRouter or external APIs
- ❌ No telemetry/analytics to third parties
- ✅ All processing on user's hardware (Ollama/llama.cpp)
- ✅ All data stays on user's network

#### Opt-In Remote Mode
```bash
PRIVACY_LOCAL_ONLY=false
OPENROUTER_API_KEY=sk-your-key
```

When enabled:
- User explicitly opts in to remote LLM calls
- Only **transformed excerpts** sent (not full textbook passages)
- OpenRouter privacy policy applies: https://openrouter.ai/privacy

### User Data

#### What We Store
- **Student mastery data**: Per-concept mastery scores (BKT/IRT)
- **Exercise responses**: Correctness, timestamps
- **Query logs**: User questions for RAG improvement (optional)

#### What We DON'T Store
- Personal identifiable information (PII) - by design
- Email, names, ages - not collected
- Browsing history outside the app

#### Data Retention
- **Local deployment**: All data stays on user's machine/server
- **Deletion**: Users can delete `data/` folder to purge all data
- **Export**: Students can export their mastery data (JSON)

### COPPA / FERPA / GDPR Considerations

This is a **self-hosted PoC**. Compliance depends on deployment:

#### For Educators/Institutions:
- **FERPA (US)**: Student education records - ensure local deployment or FERPA-compliant hosting
- **COPPA (US)**: For students under 13 - enable `PRIVACY_LOCAL_ONLY=true` and do not collect PII
- **GDPR (EU)**: Personal data - enable data export/deletion, document processing purposes

#### Our Recommendations:
1. **Deploy locally** (schools host their own instance)
2. **Enable local-only mode** for K-12 students
3. **Disable telemetry** via `PRIVACY_NO_TRACKING=true`
4. **Review logs** - ensure no PII in logs before sharing for debugging

---

## Third-Party Services & Data Flow

### When `PRIVACY_LOCAL_ONLY=true` (Default)
| Service | Data Sent | Purpose |
|---------|-----------|---------|
| Ollama (local) | Prompts with transformed excerpts | LLM inference |
| Neo4j (local) | Knowledge graph | Graph storage |
| Qdrant (local) | Embeddings + text chunks | Vector search |
| **External APIs** | **NONE** | N/A |

### When `PRIVACY_LOCAL_ONLY=false` (Opt-In)
| Service | Data Sent | Purpose |
|---------|-----------|---------|
| OpenRouter | Minimal prompts (<500 tokens) | Remote LLM fallback |
| *(User-configured)* | Transformed excerpts only | Edge induction, QA |

**OpenRouter Privacy**: https://openrouter.ai/privacy
- OpenRouter may log requests per their policy
- We send only **transformed concepts** (e.g., "photosynthesis", "cellular respiration"), not full textbook pages

---

## Security Best Practices

### API Keys
- **Never commit** `.env` to version control (in `.gitignore`)
- Use `.env.example` as template
- Rotate OpenRouter keys regularly if using remote mode

### Docker Security
- **Neo4j password**: Change default `password` in production
- **Network isolation**: Use Docker networks (already configured)
- **Volume permissions**: Ensure proper file permissions on `data/` mounts

### LLM Prompt Injection
- **Input sanitization**: All user queries sanitized before RAG/LLM
- **Output filtering**: Responses checked for age-appropriate content
- **System prompts**: Instruct LLMs to stay on-topic (education)

---

## Audit Log

For institutions requiring audit trails:

```bash
# Enable detailed logging
LOG_LEVEL=DEBUG

# Logs stored in
logs/debug.log      # All application logs
logs/error.log      # Errors only
```

Logged events:
- User queries and retrieved concepts
- Exercise attempts (correctness, concept IDs)
- LLM calls (prompts, responses, latency)
- Graph modifications (teacher edits)

**Note**: Ensure logs do not contain PII before sharing.

---

## Contact for Compliance Questions

- **GitHub Issues**: [Report compliance concerns](https://github.com/yourusername/adaptive-knowledge-graph/issues)
- **Email**: your.email@example.com

---

## Updates to this Policy

Last updated: 2025-01-13

We will update this document when:
- Adding new third-party services
- Changing data storage/processing
- New licensing information from OpenStax

Check commit history for changes: `git log -- COMPLIANCE.md`
