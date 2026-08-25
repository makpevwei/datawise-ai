# Quick Reference – RAG Assistant Setup

## One-Time Setup (2 minutes)

```bash
# 1. Navigate to project
cd /Users/rume/Desktop/ReadyTensor/rt-aaidc-project1-template-main

# 2. Activate venv
source ../.venv_py311/bin/activate

# 3. Add API key to .env (choose one):
echo "GOOGLE_API_KEY=your-key-here" >> .env
# OR: echo "GROQ_API_KEY=your-key-here" >> .env
# OR: echo "OPENAI_API_KEY=your-key-here" >> .env
```

## Run the Assistant

```bash
# From rt-aaidc-project1-template-main/
python src/app.py

# Then type questions:
# "What is machine learning?"
# "Explain neural networks"
# Type 'quit' to exit
```

## Add Your Documents

```bash
# Copy PDFs, markdown, or text files to data/
cp ~/Documents/MyPaper.pdf data/
cp ~/Notes/ideas.md data/
echo "Your content" > data/notes.txt

# Run app to ingest:
python src/app.py
```

## Key Commands

| Task | Command |
|------|---------|
| Run assistant | `python src/app.py` |
| View logs | `cat .chroma_data/` (metadata) |
| Reset vector DB | `rm -rf .chroma_data/` |
| Check dependencies | `pip list \| grep -E "chromadb\|langchain\|torch"` |
| View API key | `grep "API_KEY" .env` |

## Supported Formats

- ✓ `.txt` – Plain text
- ✓ `.md` – Markdown
- ✓ `.pdf` – PDF (auto-extracts text)

## LLM Priority

App tries in order:
1. Google Gemini (GOOGLE_API_KEY)
2. Groq (GROQ_API_KEY)
3. OpenAI (OPENAI_API_KEY)

Set any one in `.env` to get started.

## Getting API Keys

- **Google**: https://aistudio.google.com/app/apikey (free tier)
- **Groq**: https://console.groq.com/keys (free tier)
- **OpenAI**: https://platform.openai.com/api-keys (paid, $5 free trial)

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Import hangs | Normal on first run (30s+), be patient |
| "No API key found" | Run: `echo "GOOGLE_API_KEY=your-key" >> .env` |
| Vector DB error | Run: `rm -rf .chroma_data/` and restart |
| Out of memory | Reduce chunk_size in `src/vectordb.py` |

## Project Structure

```
rt-aaidc-project1-template-main/
├── src/
│   ├── app.py              # Main RAG app
│   └── vectordb.py         # Vector DB wrapper
├── data/                   # Your documents here
├── .env                    # API keys
├── requirements.txt        # Dependencies
└── README.md               # Full docs
```

## Environment

- Python: 3.11.14
- Venv: `.venv_py311/` (parent directory)
- OS: macOS
- Status: ✅ Ready to use

## File Locations

```
/Users/rume/Desktop/ReadyTensor/
├── .venv_py311/                    # Python environment (shared)
├── rt-aaidc-project1-template-main/ # RAG project (use this)
│   ├── src/app.py
│   ├── src/vectordb.py
│   ├── .env                        # Add your API key here
│   ├── data/                       # Add documents here
│   └── .chroma_data/               # Vector DB (auto-created)
└── SETUP_COMPLETE.md               # Full summary
```

## Next: Your Report

For your documentation, include:

1. **Architecture diagram**: Show the pipeline flow (doc → chunks → embeddings → search → LLM)
2. **Setup instructions**: Reference this file + README.md
3. **Example runs**: Show sample questions and answers
4. **Code snippets**: Highlight `app.py` and `vectordb.py`
5. **Performance notes**: Chunk size, retrieval count, embedding model
6. **Future enhancements**: API wrapper, web UI, streaming, fine-tuning

---

**Last Updated**: January 3, 2026
**Status**: ✅ Production Ready
**Python**: 3.11.14
**Venv**: `.venv_py311`
