"""
Quickstart: Shekel + Langfuse
==============================

Minimal example to get started with Langfuse integration.

Setup:
------
1. pip install shekel[langfuse] shekel[openai]
2. Set environment variables:
   - OPENAI_API_KEY
   - LANGFUSE_PUBLIC_KEY
   - LANGFUSE_SECRET_KEY
"""

import os

from langfuse import Langfuse
from openai import OpenAI

from shekel import budget
from shekel.integrations import AdapterRegistry
from shekel.integrations.langfuse import LangfuseAdapter

# 1. Initialize Langfuse (once at app startup)
lf = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
)

# 2. Register Shekel adapter (once at app startup)
adapter = LangfuseAdapter(client=lf, trace_name="my-app")
AdapterRegistry.register(adapter)

# 3. Use budgets as normal - costs flow to Langfuse automatically!
client = OpenAI()

with budget(max_usd=1.00, name="user-query") as b:
    response = client.chat.completions.create(
        model="gpt-4o-mini", messages=[{"role": "user", "content": "Hello!"}]
    )
    print(f"Response: {response.choices[0].message.content}")
    print(f"Cost: ${b.spent:.4f}")

# 4. Flush before exit (important!)
lf.flush()

print("\n✅ Check Langfuse UI for trace 'my-app' with cost metadata!")
