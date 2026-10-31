import asyncio

from db import db, lifespan
from main import PERMISSIONS, app


async def main() -> None:
    async with lifespan(app):
        for name, permissions in PERMISSIONS.items():
            await db().roles.update_one(
                {"name": name},
                {
                    "$set": {
                        "name": name,
                        "permissions": sorted(permissions),
                    }
                },
                upsert=True,
            )
        print("Roles seeded successfully.")


if __name__ == "__main__":
    asyncio.run(main())
