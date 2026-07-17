"""Root entry point — delegates to app.main."""

import asyncio

from app.main import main

if __name__ == "__main__":
    asyncio.run(main())
