"""Run the matcher end-to-end from the terminal: python scripts/try.py <amazon url or ASIN> [...]"""
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import http, service  # noqa: E402

ICON = {"in_stock": "●", "out_of_stock": "◐", "not_listed": "○", "error": "!"}


async def main(args: list[str]) -> None:
    for a in args:
        url = a if "/" in a else f"https://www.amazon.in/dp/{a}"
        try:
            r = await service.match(url)
        except Exception as e:
            print(f"\n{a}: ERROR {e}")
            continue
        s = r.source
        print(f"\n{s.platform_id} [{s.category.value}] {s.title[:90]}")
        print(f"   brand={s.brand} ram={s.ram_gb} storage={s.storage_gb} screen={s.screen_inches} "
              f"colour={s.colour} gender={s.gender} type={s.product_type} codes={s.model_codes}  ({r.elapsed_ms} ms)")
        for p in r.results:
            line = f"   {ICON[p.status.value]} {p.platform:8} {p.status.value:12}"
            if p.match:
                line += f" [{p.confidence}] {p.match.title[:70]}  {p.match.colour or ''}  {p.match.url}"
            if p.error:
                line += f" {p.error}"
            print(line)
            print(f"        query={p.search_query!r} seen={p.candidates_seen} notes={p.notes}")
            if p.match:
                print("        " + "; ".join(f"{c.name}:{'✓' if c.ok else '✗'}" + (f"({c.note})" if c.note else "") for c in p.checks))
            elif p.near_misses:
                for m in p.near_misses[:2]:
                    bad = [f"{c.name}: {c.source} vs {c.candidate} {c.note or ''}" for c in m.checks if not c.ok and c.required]
                    print(f"        near miss: {m.spec.title[:60]} -> {bad}")
    await http.close()


asyncio.run(main(sys.argv[1:]))
