import asyncio
import os
from pipeline import UnifiedAgent, Config

async def test_connectivity():
    print(">>> Testing Coding Plan Connectivity...")
    
    # Temporarily reduce jitter for testing
    Config.MIN_JITTER = 2
    Config.MAX_JITTER = 5
    
    agent = UnifiedAgent(
        model_name=Config.INITIAL_MODEL,
        system_instruction="You are a helpful assistant. Respond with 'PONG' and the model name used."
    )
    
    try:
        print(f"Calling {Config.INITIAL_MODEL}...")
        res = await agent.call("PING")
        print(f"Response: {res}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    if not os.environ.get("CODING_PLAN_API_KEY"):
        print("Please set CODING_PLAN_API_KEY first.")
    else:
        asyncio.run(test_connectivity())
