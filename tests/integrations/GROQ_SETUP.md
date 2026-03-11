# Groq Integration Setup

This guide explains how to use Groq API for real LLM integration testing in shekel.

## 🔐 Security First

**NEVER commit your API key to GitHub!**

### Local Setup (Development)

1. **Copy the example file:**
```bash
cp .env.example .env
```

2. **Add your Groq API key** to `.env`:
```bash
GROQ_API_KEY=gsk_your_key_here
```

3. **.env is automatically ignored by git:**
```bash
# Verify it's in .gitignore
grep ".env" .gitignore
```

4. **Load environment variables in Python:**
```python
import os
from dotenv import load_dotenv

load_dotenv()  # Loads from .env file
groq_key = os.getenv("GROQ_API_KEY")
```

## 🚀 Running Tests Locally

### With Groq API Key (Real LLM Testing)

```bash
# Load .env and run Groq tests
pytest tests/integrations/test_groq_integration.py -v
```

**Result:**
- ✅ Real LLM API calls
- ✅ Budget tracking with actual token usage
- ✅ Multiple model testing

### Without API Key (Mock Only)

```bash
# Tests gracefully skip real Groq tests
pytest tests/integrations/test_groq_integration.py -v
# Result: 1 passed, 4 skipped
```

## 🔧 GitHub Actions Setup (CI/CD)

### Adding API Key to GitHub Secrets

1. Go to: **Settings → Secrets and variables → Actions**

2. Create new secret:
   - **Name:** `GROQ_API_KEY`
   - **Value:** Your API key (from .env)

3. In workflow, use it:
```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run Groq tests
        env:
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
        run: pytest tests/integrations/test_groq_integration.py -v
```

## 📊 What Gets Tested

### Real Groq Tests (with API key)
- ✅ Budget tracking with real API inference
- ✅ Token counting accuracy
- ✅ Multiple model support (mixtral, llama2)
- ✅ Budget enforcement with real costs

### Mock Tests (always run)
- ✅ Budget mechanics without dependencies
- ✅ Graceful degradation when API unavailable

## 🛑 Rate Limits

Groq free tier: **30 requests/minute**

Shekel tests use < 5 requests per run, so no issues.

## 🔍 Troubleshooting

### "Groq API not available"
- Check `.env` file exists and has correct key
- Load with: `source .env` (bash)
- Verify: `echo $GROQ_API_KEY`

### "Invalid API Key"
- Go to https://console.groq.com
- Regenerate key if needed
- Update .env

### "Rate limit exceeded"
- Each request counts as 1/30 per minute
- Wait a minute or adjust test frequency

## 📖 Get Groq API Key

Free tier: https://console.groq.com

- No credit card required
- 30 requests/minute
- Multiple model access
- Perfect for testing

## 🔄 Environment Variable Loading

### For Tests to Find API Key

```python
import os
from dotenv import load_dotenv

# At test start
load_dotenv()
api_key = os.getenv("GROQ_API_KEY")

# Or in pytest fixture
@pytest.fixture
def groq_api_key():
    load_dotenv()
    return os.getenv("GROQ_API_KEY")
```

## 📝 Example .env

```bash
# .env (NEVER COMMIT THIS)
GROQ_API_KEY=gsk_your_actual_key_here

# .env.example (SAFE TO COMMIT)
GROQ_API_KEY=your_groq_api_key_here
```

## ✅ Best Practices

1. **Local:** Use .env file for API keys
2. **CI/CD:** Use GitHub Secrets
3. **Rotation:** Regenerate keys periodically
4. **Testing:** Mock tests for CI, real tests optional
5. **Documentation:** .env.example shows structure

---

**Next Steps:**
1. ✅ API key stored in .env (secure)
2. 📝 Add GROQ_API_KEY to GitHub Secrets
3. 🧪 Run Groq tests locally
4. 🚀 Merge to main and see CI run
