# Historical pipeline patch: preserve exact aligned calendar dates

**Problem:** The historical `src/inspect_and_prepare.py` assigned `date=NaT` and `is_weekend=NA` to every record whenever the phone-study-day axis was numeric, even when the explicitly matched `timeframe_date` was available.

## Replace this exact old block

```python
else:
    base["day"] = base["source_day_numeric"]
    base["date"] = pd.NaT
    base["is_weekend"] = pd.Series(pd.NA, index=base.index, dtype="boolean")
```

## With this corrected block

```python
else:
    base["day"] = base["source_day_numeric"]
    # Only use dates already aligned by the participant+day timeframe merge.
    # Do not invent dates for rows lacking matched timeframes.
    base["date"] = (
        pd.to_datetime(base["timeframe_date"], errors="coerce")
        if "timeframe_date" in base else pd.NaT
    )
    base["is_weekend"] = (
        (base["date"].dt.dayofweek >= 5)
        .where(base["date"].notna())
        .astype("boolean")
    )
```

The corrected block was applied and empirically checked in an isolated working copy on 17 October 2026:
- `date` non-missing before: 0 / 3,255.
- `date` non-missing after: 1,856 / 3,255.
- `is_weekend` non-missing after: 1,856 / 3,255.
- `is_weekend=True`: 399 (within aligned dates).
- Primary outcome-and-exposure complete days: unchanged at 1,806.
- 76 automated tests passed.

**Scientific caveat:** A calendar date absent in the source-aligned timeframe remains missing; the patch does not fill gaps from a fixed day-zero assumption. New weekend-adjusted statistical model estimates have not been computed. This is a patch instruction until the historical pipeline is fully migrated to the GitHub repository.
