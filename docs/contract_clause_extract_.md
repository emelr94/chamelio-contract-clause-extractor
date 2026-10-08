# AI Builder

# Contract Clause Extractor - Take Home Assignment

## Overview

Build a FastAPI service that extracts and structures key clauses from legal contracts using LLM APIs. This assignment reflects real work you'd do at Chamelio - integrating AI into production systems that legal teams rely on.

**Time Estimate:** 3-4 hours

**AI Tools:** Encouraged! We use Cursor, Claude, and other AI tools daily. Show us how you leverage them effectively. It’s gonna be part of our follow-up interview.

## What We're Looking For

- **Clean, production-ready code** - not perfect, but something you'd be comfortable shipping
- **Good engineering decisions** - AI debates, data modeling, architecture, potential pitfalls, testing approach
- **Clear communication** - Diagram representing the final solution.

## Requirements

### Core Features (Must Have)

Build a FastAPI application that:

1. **Accepts contract documents** via POST endpoint and return a JSON representing the document broken into legal clauses.
    - Support PDF processing
    - Endpoint: `POST /api/extract`
    
    **Returns structured JSON** with:
    
    - all document clauses
    - metadata
    
    **Stores results** in a database
    
2. **Retrieval endpoint**
    - `GET /api/extractions/{document_id}` - get extraction results
    - `GET /api/extractions` - list all extractions (paginated)

### Technical Requirements

- FastAPI framework
- Pydantic for data validation
- Database of your choice (SQLite is fine)
- docker file for installation and running

### Bonus Points (Optional)

- DocX and other types processing
- Basic tests
- use LLMs

## Submission Instructions

1. **Code**: Share a Zip/GitHub/GitLab repo (public or private with access)
2. **README**: Include:
    - Setup instructions (how to run locally)
    - Your design decisions and tradeoffs
    - What you'd improve with more time
    - Any assumptions you made
3. **Demo**: A script/notebook to run e2e demo

## Evaluation Criteria

We'll be looking at:

| Criteria | Weight | What We're Assessing |
| --- | --- | --- |
| **Code Quality** | 25% | Structure, readability, pythonic patterns |
| **AI Usage** | 30% | Prompting, discussions, steps |
| **API Design** | 20% | FastAPI best practices, validation, responses |
| **Data Modeling** | 15% | Pydantic schemas, database design |
| **Documentation** | 10% | README, code comments, API docs |

## Tips for Success

✅ **DO:**

- Use AI tools to move faster - we want to see how you work with them
- Make pragmatic tradeoffs (document what you'd do differently with more time)
- Focus on the core features first, then add bonuses if time permits
- Write code you'd be proud to have reviewed by your team

❌ **DON'T:**

- Over-engineer - we value shipping over perfection
- Spend more than 4-5 hours - we respect your time
- Stress about making it "perfect" - good enough to ship is the goal

Remember: The discussion > Code 

## Questions?

Email us at oran.bendaivd@chamelio.ai - we're happy to clarify anything!

---

**Ready to ship?** We're excited to see what you build! 🚀