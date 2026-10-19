"""What does Builder search do when the inference host is down? Read-only; dead-port client."""
import asyncio, time
from neo4j import AsyncGraphDatabase
from openai import AsyncOpenAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from src.jd_bank.composer.search import search_similar_jds
from src.jd_bank.embeddings.client import EmbedClient
from src.settings import get_settings


async def main():
    st = get_settings()
    eng = create_async_engine(st.database_url)
    mk = async_sessionmaker(eng, expire_on_commit=False)
    drv = AsyncGraphDatabase.driver(st.neo4j_uri, auth=(st.neo4j_user, st.neo4j_password))
    for q in ("Financial Assistant", "Financial", "someone who processes invoices"):
        dead = EmbedClient(client=AsyncOpenAI(base_url="http://127.0.0.1:9/v1", api_key="x", max_retries=0))
        async with mk() as s:
            await s.execute(text("SET TRANSACTION READ ONLY"))
            t = time.perf_counter()
            try:
                hits = await asyncio.wait_for(search_similar_jds(q, embed_client=dead, neo4j_driver=drv, session=s, limit=10), timeout=10.0)
                print(repr(q), "OK", len(hits), [h.match for h in hits][:3], round(time.perf_counter() - t, 2))
            except Exception as e:  # noqa: BLE001
                print(repr(q), "RAISED", type(e).__name__, str(e)[:80], round(time.perf_counter() - t, 2))
            await s.rollback()
    await drv.close(); await eng.dispose()

asyncio.run(main())
