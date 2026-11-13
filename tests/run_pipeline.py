import asyncio
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from mock_genai import install_mock_genai

install_mock_genai()

import pipeline


def main():
    if not os.environ.get("MOCK_SERVER_PORT"):
        raise RuntimeError("MOCK_SERVER_PORT is required by this test adapter.")

    pipeline.Config.load_config()
    mock_base_url = f"http://127.0.0.1:{os.environ['MOCK_SERVER_PORT']}/v1"
    pipeline.Config.CODING_PLAN_BASE_URL = mock_base_url
    pipeline.Config.SAKURA_BASE_URL = mock_base_url
    pipeline.Config.DEEPSEEK_BASE_URL = mock_base_url
    pipeline.Config.MIN_JITTER = 0.01
    pipeline.Config.MAX_JITTER = 0.02

    asyncio.run(pipeline.TranslationPipeline().run_all())


if __name__ == "__main__":
    main()
