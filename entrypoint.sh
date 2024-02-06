#!/bin/bash

# Check if OPENAI_API_KEY is set and not empty
if [ -n "$OPENAI_API_KEY" ]; then
    # If OPENAI_API_KEY is set, run demo_gpt4v_som.py
    python ./demo_gpt4v_som.py
else
    # If OPENAI_API_KEY is not set, run demo_som.py
    python ./demo_som.py
fi
